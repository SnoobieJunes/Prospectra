# 2026-07-13 (P1): Column profiler — the numbers behind the profile cards (data grid pane now,
# flow-canvas profile pane in P2, mining pre-pass in P3). Pure SQL against DuckDB, no Qt.
# Why sampled: profiling is interactive; above `max_rows` we profile a seeded reservoir sample
# and say so (`sampled=True`) instead of silently scanning everything.

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

from prospectra.core.sampling import sample_rel
from prospectra.core.sqlutil import ident

_NUMERIC_PREFIXES = (
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
)


@dataclass(frozen=True)
class Bin:
    label: str
    count: int


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    dtype: str
    null_count: int
    distinct: int
    numeric: bool
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    std: float | None = None
    bins: list[Bin] = field(default_factory=list)  # numeric histogram
    top: list[Bin] = field(default_factory=list)  # categorical top values


@dataclass(frozen=True)
class TableProfile:
    row_count: int
    sampled: bool
    sample_size: int
    columns: list[ColumnProfile]


def _f(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def profile_relation(
    cursor: duckdb.DuckDBPyConnection,
    rel: str,
    *,
    max_rows: int = 50_000,
    bins: int = 10,
    seed: int = 42,
) -> TableProfile:
    """Profile a relation (view name or parenthesized subquery)."""
    row = cursor.execute(f"SELECT count(*) FROM {rel}").fetchone()
    total = int(row[0]) if row else 0
    sampled = total > max_rows
    src = sample_rel(rel, max_rows, seed) if sampled else rel
    sample_size = max_rows if sampled else total

    described = cursor.execute(f"DESCRIBE SELECT * FROM {rel} LIMIT 0").fetchall()
    columns: list[ColumnProfile] = []
    for name, dtype, *_ in described:
        columns.append(_profile_column(cursor, src, str(name), str(dtype), bins))
    return TableProfile(row_count=total, sampled=sampled, sample_size=sample_size, columns=columns)


def _profile_column(
    cursor: duckdb.DuckDBPyConnection, src: str, name: str, dtype: str, bins: int
) -> ColumnProfile:
    col = ident(name)
    numeric = dtype.upper().startswith(_NUMERIC_PREFIXES)
    base = cursor.execute(
        f"SELECT count(*) - count({col}), approx_count_distinct({col}) FROM {src}"
    ).fetchone()
    null_count, distinct = (int(base[0]), int(base[1])) if base else (0, 0)

    if not numeric:
        top_rows = cursor.execute(
            f"SELECT CAST({col} AS VARCHAR) AS v, count(*) AS c FROM {src} "
            f"WHERE {col} IS NOT NULL GROUP BY v ORDER BY c DESC, v LIMIT 8"
        ).fetchall()
        top = [Bin(str(v), int(c)) for v, c in top_rows]
        return ColumnProfile(name, dtype, null_count, distinct, False, top=top)

    stats = cursor.execute(
        f"SELECT min({col}), max({col}), avg({col}), stddev({col}) FROM {src}"
    ).fetchone()
    lo, hi, mean, std = (
        (_f(stats[0]), _f(stats[1]), _f(stats[2]), _f(stats[3])) if stats else (None,) * 4
    )

    hist: list[Bin] = []
    if lo is not None and hi is not None:
        if hi > lo:
            width = (hi - lo) / bins
            rows = cursor.execute(
                f"SELECT LEAST(CAST(FLOOR((CAST({col} AS DOUBLE) - {lo}) / {width}) AS INTEGER), "
                f"{bins - 1}) AS b, count(*) AS c FROM {src} WHERE {col} IS NOT NULL "
                f"GROUP BY b ORDER BY b"
            ).fetchall()
            counts = {int(b): int(c) for b, c in rows}
            hist = [
                Bin(f"{lo + i * width:.4g} to {lo + (i + 1) * width:.4g}", counts.get(i, 0))
                for i in range(bins)
            ]
        else:
            non_null = cursor.execute(f"SELECT count({col}) FROM {src}").fetchone()
            hist = [Bin(f"{lo:.4g}", int(non_null[0]) if non_null else 0)]

    return ColumnProfile(name, dtype, null_count, distinct, True, lo, hi, mean, std, bins=hist)
