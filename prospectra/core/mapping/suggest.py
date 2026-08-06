# 2026-07-31 (P7): Match suggestions — the "everyone calls it something different" solver.
#
# Two scorers, because names and values fail differently:
#   * `suggest_matches` reads the NAMES: token-Jaccard after camel/snake splitting and
#     abbreviation expansion (weight 0.5, the part difflib alone cannot do), raw
#     SequenceMatcher similarity (0.3), and dtype compatibility (0.2).
#   * `suggest_from_values` reads the DATA: overlap of sampled distinct values. This is the one
#     that matches `c1` to `colour_code` — names lie, values don't.
#
# Suggestions are ALWAYS proposals the user accepts; nothing here is ever applied silently.

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

import duckdb

from prospectra.core.mapping.abbrev import normalized_tokens
from prospectra.core.sqlutil import ident

DEFAULT_MIN_CONFIDENCE = 0.45

_NUMERIC = (
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
    "FLOAT",
    "DOUBLE",
    "DECIMAL",
    "REAL",
)
_TEMPORAL = ("DATE", "TIMESTAMP", "TIME")


@dataclass(frozen=True)
class Suggestion:
    source: str
    target: str
    confidence: float  # 0..1
    reason: str  # a sentence the user can judge ("names share 'product name'; types agree")


def _dtype_family(dtype: str) -> str:
    upper = dtype.upper()
    if any(upper.startswith(t) for t in _NUMERIC):
        return "numeric"
    if any(upper.startswith(t) for t in _TEMPORAL):
        return "temporal"
    if upper.startswith(("VARCHAR", "TEXT", "STRING", "CHAR")):
        return "text"
    return "unknown"


def _dtype_score(a: str, b: str) -> float:
    family_a, family_b = _dtype_family(a), _dtype_family(b)
    if "unknown" in (family_a, family_b):
        return 0.5  # no evidence either way beats a false penalty
    return 1.0 if family_a == family_b else 0.0


def _flat(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def suggest_matches(
    source_cols: list[tuple[str, str]],
    target_cols: list[tuple[str, str]],
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> list[Suggestion]:
    """Best source for each target, by name+type evidence. `(name, dtype)` pairs on both sides."""
    suggestions: list[Suggestion] = []
    for target_name, target_dtype in target_cols:
        target_tokens = set(normalized_tokens(target_name))
        best: Suggestion | None = None
        for source_name, source_dtype in source_cols:
            source_tokens = set(normalized_tokens(source_name))
            union = source_tokens | target_tokens
            jaccard = len(source_tokens & target_tokens) / len(union) if union else 0.0
            sequence = SequenceMatcher(None, _flat(source_name), _flat(target_name)).ratio()
            dtype = _dtype_score(source_dtype, target_dtype)
            confidence = 0.5 * jaccard + 0.3 * sequence + 0.2 * dtype

            if confidence >= min_confidence and (best is None or confidence > best.confidence):
                shared = source_tokens & target_tokens
                parts = []
                if shared:
                    parts.append(f"names share {' '.join(sorted(shared))!r}")
                elif sequence >= 0.6:
                    parts.append("names look alike")
                parts.append("types agree" if dtype == 1.0 else "types differ")
                best = Suggestion(
                    source=source_name,
                    target=target_name,
                    confidence=round(confidence, 3),
                    reason="; ".join(parts),
                )
        if best is not None:
            suggestions.append(best)
    return sorted(suggestions, key=lambda s: s.confidence, reverse=True)


def suggest_from_values(
    con: duckdb.DuckDBPyConnection,
    source_rel: str,
    target_rel: str,
    pairs: list[tuple[str, str]],
    sample: int = 200,
) -> list[Suggestion]:
    """Score candidate (source_col, target_col) pairs by sampled distinct-value overlap.

    Containment of the smaller side in the larger, on trimmed lower-cased text — so `c1`
    holding NVY/BLK/WHT matches `colour_code` holding the same vocabulary even though the
    names share nothing.
    """
    suggestions: list[Suggestion] = []
    for source_col, target_col in pairs:
        source_values = _sample_values(con, source_rel, source_col, sample)
        target_values = _sample_values(con, target_rel, target_col, sample)
        if not source_values or not target_values:
            continue
        overlap = len(source_values & target_values) / min(len(source_values), len(target_values))
        if overlap <= 0.0:
            continue
        suggestions.append(
            Suggestion(
                source=source_col,
                target=target_col,
                confidence=round(overlap, 3),
                reason=(
                    f"{overlap:.0%} of sampled values overlap "
                    f"({len(source_values)} vs {len(target_values)} distinct sampled)"
                ),
            )
        )
    return sorted(suggestions, key=lambda s: s.confidence, reverse=True)


def _sample_values(con: duckdb.DuckDBPyConnection, rel: str, column: str, sample: int) -> set[str]:
    rows = con.execute(
        f"SELECT DISTINCT lower(trim(CAST({ident(column)} AS VARCHAR))) FROM {rel} "
        f"WHERE {ident(column)} IS NOT NULL LIMIT {int(sample)}"
    ).fetchall()
    return {str(r[0]) for r in rows if r[0] != ""}
