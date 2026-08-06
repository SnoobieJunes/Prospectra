# 2026-07-31 (P7): MappingDoc -> one SELECT. The compiler is a projection factory: one row in,
# one row out, every output column an expression built ONLY from coerced transform args and
# properly quoted identifiers/literals. There is deliberately no way to express a row-multiplying
# operation here (split means split_part, never unnest) — that would break the one-row-in-one-
# row-out mental model the whole mapper UI rests on.
#
# NULL semantics: multi-source joins use concat_ws, which SKIPS NULLs — "a" || ' - ' || NULL is
# NULL and a product with no colourway would vanish; concat_ws(' - ', a, NULL) yields "a".
# (DuckDB quirk, asserted in tests: concat_ws over ALL-NULL sources returns '' not NULL.)
#
# `coercion_check_sql` is the "nothing is silent" half: for every field whose chain can lose a
# value (a TRY_CAST, a parse_date, …) it counts rows that went in readable and came out NULL —
# that is how "37 rows could not be read as a price" gets stated instead of silently NULLed. The
# same technique counts crosswalk misses.

from __future__ import annotations

from prospectra.core.mapping.doc import FieldMap, MappingDoc, check_type
from prospectra.core.mapping.transforms import (
    MAX_INLINE_PAIRS,
    build_step,
    coerce_step_args,
    dedupe_pairs,
    lookup_probe,
)
from prospectra.core.sqlutil import ident, str_lit


def _base_expr(field_map: FieldMap) -> str:
    if not field_map.sources:
        return str_lit(field_map.constant) if field_map.constant else "CAST(NULL AS VARCHAR)"
    if len(field_map.sources) == 1:
        return ident(field_map.sources[0])  # identity: the source's type is preserved
    columns = ", ".join(ident(s) for s in field_map.sources)
    return f"concat_ws({str_lit(field_map.join_with)}, {columns})"


# 2026-07-31 (P7): the declared type is the ONE value that reaches SQL as text rather than as a
# quoted literal or identifier, so it is re-checked HERE — the single choke point every compile
# path passes through — and not only in MappingDoc.validate(). `field_exprs` (the mapper's live
# preview) and `coercion_check_sql` both build expressions without calling validate(); with the
# check living only there, a type of "VARCHAR) AS x FROM t); COPY (...) TO '/tmp/x'; --" inside a
# SHARED project file executed arbitrary statements the moment the user pressed "Preview values"
# (DuckDB's execute() runs `;`-separated statements). Guarding the accessor makes that
# unreachable by construction rather than by remembering to validate first.
def _declared_type(doc: MappingDoc, target: str) -> str | None:
    for column in doc.target_columns:
        if column.name == target:
            check_type(column.type, column.name)
            return column.type
    return None


def _folded_expr(doc: MappingDoc, field_map: FieldMap) -> str:
    expr = _base_expr(field_map)
    for step in field_map.steps:
        expr = build_step(step.key, step.args, expr)
    declared = _declared_type(doc, field_map.target)
    # TRY_, never CAST: one unreadable value must not crash the run — it gets COUNTED instead
    # (coercion_check_sql).
    # 2026-08-05: applied whenever a type is declared. The old "skip the cast for a single
    # untouched source" shortcut meant a target declared BIGINT fed by a VARCHAR column came out
    # VARCHAR — the declared contract silently unmet, and no counter to say so.
    if declared:
        expr = f"TRY_CAST({expr} AS {declared})"
    return expr


def compile_select(doc: MappingDoc, source_rel: str, available: list[str] | None = None) -> str:
    """The mapping as one SELECT over `source_rel`.

    With `available` (the live upstream column list), unknown sources are rejected BY NAME —
    an upstream rename must produce "colourway is not a column of the input", not a raw DuckDB
    binder error three screens later.
    """
    doc.validate()
    if not doc.fields and doc.unmapped_policy != "passthrough":
        # Otherwise the emitted SQL is "SELECT  FROM rel" and DuckDB's parser error is the only
        # thing the user sees.
        raise ValueError("this mapping has no fields — map at least one target column")
    if available is not None:
        have = {c.casefold() for c in available}
        for field_map in doc.fields:
            missing = [s for s in field_map.sources if s.casefold() not in have]
            if missing:
                raise ValueError(
                    f"{field_map.target}: source column(s) not in the input: {', '.join(missing)}"
                )

    projections: list[str] = []
    # 2026-08-05: name comparisons are case-FOLDED, because SQL identifiers are case-insensitive
    # in DuckDB while Python sets are not. With exact matching, an input column `SKU` and a target
    # `sku` both survived into the projection; DuckDB then renamed one and a downstream step
    # reading `sku` silently got the passthrough value instead of the mapped one.
    mapped = {f.target.casefold() for f in doc.fields}

    if doc.unmapped_policy == "passthrough":
        if available is None:
            raise ValueError(
                "the pass-through policy needs the input's column list to know what to pass"
            )
        consumed = {s.casefold() for f in doc.fields for s in f.sources}
        # Also exclude any input column that shares a *target's* name — passing it through would
        # collide with the mapped projection of the same name.
        shadowed = [c for c in available if c.casefold() in consumed or c.casefold() in mapped]
        star = "*"
        if shadowed:
            star += " EXCLUDE (" + ", ".join(ident(c) for c in shadowed) + ")"
        projections.append(star)

    for field_map in doc.fields:
        projections.append(f"{_folded_expr(doc, field_map)} AS {ident(field_map.target)}")

    if doc.unmapped_policy == "null":
        for column in doc.target_columns:
            if column.name.casefold() not in mapped:
                check_type(column.type, column.name)
                projections.append(f"CAST(NULL AS {column.type}) AS {ident(column.name)}")

    return "SELECT\n  " + ",\n  ".join(projections) + f"\nFROM {source_rel}"


def field_exprs(doc: MappingDoc, target: str) -> tuple[str, str]:
    """(base_expr, final_expr) for one mapped target — the mapper's before/after pane."""
    for field_map in doc.fields:
        if field_map.target == target:
            return _base_expr(field_map), _folded_expr(doc, field_map)
    raise ValueError(f"nothing is mapped to {target!r}")


# Steps that can turn a readable value into NULL. Measured individually, because measuring only
# the end of the chain lies in both directions (see coercion_check_sql).
LOSSY_STEPS = frozenset({"cast", "parse_date", "date_format", "round"})


def _readable(expr: str, field_map: FieldMap) -> str:
    """ "there was something to read here" for a value about to enter a lossy step.

    Multi-source fields need the `<> ''` arm: DuckDB's concat_ws returns '' (not NULL) when every
    source is NULL, so an all-empty row looked like a readable value that the cast then destroyed
    and got reported as "could not be read" when there was nothing to read.
    """
    if len(field_map.sources) > 1:
        return f"({expr} IS NOT NULL AND {expr} <> '')"
    return f"{expr} IS NOT NULL"


def coercion_check_sql(doc: MappingDoc, rel: str) -> str:
    """One row of loss-counters over `rel`, or "" when no field can lose a value.

    2026-08-05: counted PER LOSSY STEP rather than once at the end of the chain. Comparing only
    base-vs-final was wrong twice over: a `default()` after a cast re-fills the NULLs, so real
    losses reported zero ("nothing is silent" was false); and an all-NULL multi-source row counted
    as a loss when there had been nothing to read. Each cast/parse/round now reports its own
    casualties, and the declared-type cast reports its own.

    Per lookup step, `<target>__unmatched` counts rows the crosswalk had no translation for (they
    keep their original value — the COALESCE in the lookup build — but the user is told how many).
    """
    checks: list[str] = []
    for field_map in doc.fields:
        if not (field_map.sources or field_map.constant):
            continue
        expr = _base_expr(field_map)
        lookup_seen = 0
        for step in field_map.steps:
            if step.key == "lookup":
                lookup_seen += 1
                suffix = "__unmatched" if lookup_seen == 1 else f"__unmatched_{lookup_seen}"
                probe = lookup_probe(expr, coerce_step_args(step.key, step.args))
                checks.append(
                    f"count(*) FILTER (WHERE {expr} IS NOT NULL AND {probe} IS NULL) "
                    f"AS {ident(field_map.target + suffix)}"
                )
            after = build_step(step.key, step.args, expr)
            if step.key in LOSSY_STEPS:
                checks.append(
                    f"count(*) FILTER (WHERE {_readable(expr, field_map)} AND {after} IS NULL) "
                    f"AS {ident(field_map.target + '__lost_' + step.key)}"
                )
            expr = after
        declared = _declared_type(doc, field_map.target)
        if declared:
            final = f"TRY_CAST({expr} AS {declared})"
            checks.append(
                f"count(*) FILTER (WHERE {_readable(expr, field_map)} AND {final} IS NULL) "
                f"AS {ident(field_map.target + '__lost')}"
            )
    if not checks:
        return ""
    return "SELECT " + ", ".join(checks) + f" FROM {rel}"


def compile_notes(doc: MappingDoc) -> list[str]:
    """Anything the compiled SQL does that the user has not been told — caps, mostly."""
    notes: list[str] = []
    for field_map in doc.fields:
        for step in field_map.steps:
            if step.key != "lookup":
                continue
            pairs = step.args.get("pairs") or []
            if len(pairs) > MAX_INLINE_PAIRS:
                notes.append(
                    f"{field_map.target}: the inline crosswalk keeps the first "
                    f"{MAX_INLINE_PAIRS} of {len(pairs)} pairs — put the full crosswalk "
                    "in a file to use all of it"
                )
            _kept, dropped = dedupe_pairs(list(pairs)[:MAX_INLINE_PAIRS])
            if dropped:
                notes.append(
                    f"{field_map.target}: {dropped} repeated key(s) in the crosswalk — the "
                    "first translation of each is used"
                )
    return notes
