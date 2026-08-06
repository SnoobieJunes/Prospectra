# 2026-07-31 (P7): The transform vocabulary — a descriptor, not a class (dialects.py's pattern).
#
# This is what "no raw SQL is ever typed" means concretely: a transformation is a `key` plus typed
# args in a saved document, and `coerce_args` is the INJECTION BOUNDARY — it runs before `build`,
# so `build` can never see a string where an int is declared ("40; DROP TABLE" dies here with a
# message, not in the database). Every string arg goes through `str_lit`; every choice arg is
# checked against its closed list; `build` is never serialized (the doc stores key + args only).
#
# Two honest exceptions, both deliberate (2026-08-05):
#   * `expression` IS arbitrary SQL. That is its entire purpose; it is status="advanced", hidden
#     behind a disclosure, and never suggested. The boundary claim above covers the other 18.
#   * the declared TARGET TYPE is not a transform arg — it reaches SQL as text and is guarded
#     separately by `check_type`, enforced at every compile entry point (see compile.py).
#
# DuckDB edge semantics, verified by hand against DuckDB 1.5.4 before anything was labelled
# "verified" (tests/test_mapping_transforms.py locks them):
#   * there is NO initcap() — `title` uses a list_transform lambda instead
#   * regexp_extract returns '' (not NULL) on no match; split_part past the last piece returns ''
#   * concat_ws over all-NULL sources returns '' (handled in compile.py, stated in field help)

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from prospectra.core.sqlutil import ident, str_lit

# The closed list a cast may target. `TargetColumn.type` is validated against a safe pattern, but
# the cast *transform* is stricter: a plain choice, because choices render as a dropdown.
CAST_TYPES = ("VARCHAR", "BIGINT", "DOUBLE", "DECIMAL(18,4)", "DATE", "TIMESTAMP", "BOOLEAN")

MAX_INLINE_PAIRS = 50  # beyond this, a crosswalk belongs in a file, not a form


@dataclass(frozen=True)
class ArgSpec:
    name: str
    label: str
    kind: str  # string | int | choice | pairs | path
    default: Any = ""
    choices: tuple[str, ...] = ()
    help: str = ""
    min_value: int | None = None  # int args only
    max_value: int | None = None


@dataclass(frozen=True)
class Transform:
    key: str
    label: str  # "Split and keep part"
    summary: str  # user-facing: "Split on a character, keep the Nth piece"
    args: tuple[ArgSpec, ...] = ()
    # (sql_expr, coerced_args) -> sql_expr. Never serialized; the doc stores key + args.
    build: Callable[[str, dict[str, Any]], str] = field(default=lambda expr, args: expr)
    result_type: str = "VARCHAR"
    status: str = "verified"  # verified | advanced


def coerce_args(transform: Transform, raw: dict[str, Any]) -> dict[str, Any]:
    """Typed, bounded args or a ValueError — the boundary between a document and SQL text.

    Unknown arg names are rejected (a typo'd arg silently ignored is a mapping that lies), ints
    are int()-coerced with bounds, choices must be in their closed list, and pairs must be a list
    of 2-string pairs.
    """
    known = {spec.name for spec in transform.args}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"{transform.label}: unknown argument(s) {', '.join(sorted(unknown))}")
    coerced: dict[str, Any] = {}
    for spec in transform.args:
        value = raw.get(spec.name, spec.default)
        if spec.kind == "int":
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ValueError(
                    f"{transform.label}: {spec.label} must be a whole number, got {value!r}"
                ) from None
            if spec.min_value is not None and value < spec.min_value:
                raise ValueError(f"{transform.label}: {spec.label} must be ≥ {spec.min_value}")
            if spec.max_value is not None and value > spec.max_value:
                raise ValueError(f"{transform.label}: {spec.label} must be ≤ {spec.max_value}")
        elif spec.kind == "choice":
            value = str(value)
            if value not in spec.choices:
                raise ValueError(
                    f"{transform.label}: {spec.label} must be one of {', '.join(spec.choices)}"
                )
        elif spec.kind == "pairs":
            if not isinstance(value, list) or not all(
                isinstance(p, (list, tuple)) and len(p) == 2 for p in value
            ):
                raise ValueError(f"{transform.label}: {spec.label} must be a list of [from, to]")
            value = [(str(a), str(b)) for a, b in value]
        else:  # string | path
            value = str(value)
        coerced[spec.name] = value
    return coerced


# -- lookup helpers (also used by compile.py to count crosswalk misses) --------------------------


def crosswalk_table(file_path: str) -> str:
    """The deterministic name a file-backed crosswalk is materialized under (by Node.prepare)."""
    digest = hashlib.sha1(file_path.encode("utf-8")).hexdigest()[:12]
    return f"xwalk_{digest}"


def dedupe_pairs(pairs: list[Any]) -> tuple[list[tuple[str, str]], int]:
    """(first-wins unique pairs, number dropped). DuckDB's MAP refuses duplicate keys outright.

    2026-08-05: without this, pasting a crosswalk containing the same key twice compiled fine and
    then died mid-run with `InvalidInputException: Map keys must be unique` — the file-backed
    path had always deduped, the paste-a-list path had not.
    """
    seen: dict[str, str] = {}
    dropped = 0
    for pair in pairs:
        key, value = str(pair[0]), str(pair[1])
        if key in seen:
            dropped += 1
            continue
        seen[key] = value
    return list(seen.items()), dropped


def lookup_probe(expr: str, args: dict[str, Any]) -> str:
    """The raw map lookup — NULL on a miss. `build` COALESCEs it; the miss-counter reads it raw."""
    raw_pairs = list(args.get("pairs") or [])[:MAX_INLINE_PAIRS]
    pairs, _dropped = dedupe_pairs(raw_pairs)
    file_path = str(args.get("file") or "").strip()
    if file_path:
        table = crosswalk_table(file_path)
        map_expr = f"(SELECT map(list(map_key), list(map_value)) FROM {table})"
    elif pairs:
        entries = ", ".join(f"{str_lit(k)}: {str_lit(v)}" for k, v in pairs)
        map_expr = f"MAP {{{entries}}}"
    else:
        raise ValueError("Translate values: add at least one pair, or point at a crosswalk file")
    return f"map_extract({map_expr}, {expr})[1]"


def coerce_step_args(key: str, raw_args: dict[str, Any]) -> dict[str, Any]:
    """Coerced args for a step key — the boundary, exposed for callers that need args not SQL.

    2026-08-05: `coercion_check_sql` called `lookup_probe` with RAW args, which is precisely the
    hole the module header claims cannot exist. A doc with numeric crosswalk keys passed
    validate() (which coerces a copy), compiled, wrote its output, then crashed in `str_lit`.
    """
    transform = TRANSFORMS_BY_KEY.get(key)
    if transform is None:
        raise ValueError(f"unknown transform {key!r}")
    return coerce_args(transform, raw_args)


def _build_lookup(expr: str, args: dict[str, Any]) -> str:
    # A miss keeps the original value (never silently blanks it); misses are COUNTED by
    # coercion_check_sql so "213 rows had no translation" gets stated.
    return f"COALESCE({lookup_probe(expr, args)}, {expr})"


def _build_title(expr: str, args: dict[str, Any]) -> str:
    # DuckDB 1.5 has no initcap(); a regexp \U backreference is PCRE, not RE2. This lambda form
    # was executed against DuckDB before the transform was labelled "verified".
    return (
        f"array_to_string(list_transform(string_split(lower({expr}), ' '), "
        f"w -> upper(substr(w, 1, 1)) || substr(w, 2)), ' ')"
    )


def _build_expression(expr: str, args: dict[str, Any]) -> str:
    sql = str(args.get("sql", "")).strip()
    if not sql:
        raise ValueError("Custom expression: the SQL is empty")
    if "{value}" not in sql:
        raise ValueError("Custom expression: reference the incoming value as {value}")
    return "(" + sql.replace("{value}", f"({expr})") + ")"


TRANSFORMS: tuple[Transform, ...] = (
    Transform(
        "trim", "Trim spaces", "Remove spaces from both ends", build=lambda e, a: f"trim({e})"
    ),
    Transform("upper", "UPPERCASE", "Convert to upper case", build=lambda e, a: f"upper({e})"),
    Transform("lower", "lowercase", "Convert to lower case", build=lambda e, a: f"lower({e})"),
    Transform("title", "Title Case", "Capitalize Each Word", build=_build_title),
    Transform(
        "truncate",
        "Truncate",
        "Keep only the first N characters",
        args=(ArgSpec("length", "Max length", "int", 40, min_value=1),),
        build=lambda e, a: f"substr({e}, 1, {a['length']})",
    ),
    Transform(
        "prepend",
        "Prepend text",
        "Add text before the value (empty values stay empty)",
        args=(ArgSpec("text", "Text", "string"),),
        build=lambda e, a: f"{str_lit(a['text'])} || {e}",
    ),
    Transform(
        "append",
        "Append text",
        "Add text after the value (empty values stay empty)",
        args=(ArgSpec("text", "Text", "string"),),
        build=lambda e, a: f"{e} || {str_lit(a['text'])}",
    ),
    Transform(
        "replace",
        "Find & replace",
        "Replace every occurrence of a text",
        args=(ArgSpec("find", "Find", "string"), ArgSpec("with", "Replace with", "string")),
        build=lambda e, a: f"replace({e}, {str_lit(a['find'])}, {str_lit(a['with'])})",
    ),
    Transform(
        "split_part",
        "Split and keep part",
        "Split on a character, keep the Nth piece",
        args=(
            ArgSpec("sep", "Split on", "string", "-"),
            ArgSpec(
                "index",
                "Keep piece #",
                "int",
                1,
                min_value=1,
                help="1 = first piece. Past the last piece gives an empty value.",
            ),
        ),
        build=lambda e, a: f"split_part({e}, {str_lit(a['sep'])}, {a['index']})",
    ),
    Transform(
        "regex_extract",
        "Extract by pattern",
        "Keep what a regular expression captures",
        args=(
            ArgSpec("pattern", "Pattern", "string"),
            ArgSpec(
                "group",
                "Group #",
                "int",
                1,
                min_value=0,
                help="0 = the whole match. No match gives an empty value.",
            ),
        ),
        build=lambda e, a: f"regexp_extract({e}, {str_lit(a['pattern'])}, {a['group']})",
    ),
    Transform(
        "regex_replace",
        "Replace by pattern",
        "Replace what a regular expression matches",
        args=(ArgSpec("pattern", "Pattern", "string"), ArgSpec("with", "Replace with", "string")),
        build=lambda e, a: (
            f"regexp_replace({e}, {str_lit(a['pattern'])}, {str_lit(a['with'])}, 'g')"
        ),
    ),
    Transform(
        "pad",
        "Pad",
        "Pad to a fixed width",
        args=(
            ArgSpec("length", "Width", "int", 8, min_value=1),
            ArgSpec("char", "Pad with", "string", "0"),
            ArgSpec("side", "Side", "choice", "left", ("left", "right")),
        ),
        build=lambda e, a: (
            f"{'lpad' if a['side'] == 'left' else 'rpad'}({e}, {a['length']}, {str_lit(a['char'])})"
        ),
    ),
    Transform(
        "default",
        "Default if empty",
        "Use a fallback when the value is missing",
        args=(ArgSpec("value", "Default", "string"),),
        build=lambda e, a: f"coalesce({e}, {str_lit(a['value'])})",
    ),
    Transform(
        "round",
        "Round",
        "Round a number to N decimal places",
        args=(ArgSpec("places", "Decimal places", "int", 2, min_value=0, max_value=12),),
        build=lambda e, a: f"round(TRY_CAST({e} AS DOUBLE), {a['places']})",
        result_type="DOUBLE",
    ),
    Transform(
        "lookup",
        "Translate values",
        "Map values through a crosswalk (Navy → NVY)",
        args=(
            ArgSpec(
                "pairs",
                "Pairs",
                "pairs",
                [],
                help=f"Up to {MAX_INLINE_PAIRS} from→to pairs; more belongs in a file",
            ),
            ArgSpec(
                "file",
                "Crosswalk file",
                "path",
                "",
                help="A 2-column CSV (from, to); used instead of pairs when set",
            ),
        ),
        build=_build_lookup,
    ),
    Transform(
        "cast",
        "Change type",
        "Read the value as a different type (unreadable ones are counted)",
        args=(ArgSpec("type", "Type", "choice", "VARCHAR", CAST_TYPES),),
        build=lambda e, a: f"TRY_CAST({e} AS {a['type']})",
    ),
    Transform(
        "parse_date",
        "Read as date",
        "Parse text into a date using a format",
        args=(
            ArgSpec(
                "format",
                "Format",
                "string",
                "%Y-%m-%d",
                help="e.g. %d/%m/%Y — a wrong format empties the column; the preview "
                "counts how many values could not be read",
            ),
        ),
        build=lambda e, a: f"try_strptime({e}, {str_lit(a['format'])})",
        result_type="TIMESTAMP",
    ),
    Transform(
        "date_format",
        "Format date",
        "Write a date out in a format",
        args=(ArgSpec("format", "Format", "string", "%Y-%m-%d"),),
        build=lambda e, a: f"strftime(TRY_CAST({e} AS TIMESTAMP), {str_lit(a['format'])})",
    ),
    Transform(
        "expression",
        "Custom expression",
        "Raw SQL over {value} — for people who asked for it",
        args=(
            ArgSpec(
                "sql",
                "SQL expression",
                "string",
                "",
                help="Reference the incoming value as {value}. This is the ONE escape "
                "hatch that is raw SQL; it is never suggested automatically.",
            ),
        ),
        build=_build_expression,
        status="advanced",
    ),
)

TRANSFORMS_BY_KEY: dict[str, Transform] = {t.key: t for t in TRANSFORMS}


def build_step(key: str, raw_args: dict[str, Any], expr: str) -> str:
    """Coerce, then build — the only way compile.py applies a step."""
    transform = TRANSFORMS_BY_KEY.get(key)
    if transform is None:
        raise ValueError(f"unknown transform {key!r}")
    return transform.build(expr, coerce_args(transform, raw_args))


__all__ = [
    "CAST_TYPES",
    "MAX_INLINE_PAIRS",
    "TRANSFORMS",
    "TRANSFORMS_BY_KEY",
    "ArgSpec",
    "Transform",
    "build_step",
    "coerce_args",
    "crosswalk_table",
    "ident",
    "lookup_probe",
]
