# 2026-07-13 (P1): Reservoir sampling as a SQL relation transformer. `rel` is a view name or a
# parenthesized subquery; the result composes into any downstream SQL (profiler, mining engine).
# Why reservoir: exact sample size regardless of input cardinality; REPEATABLE-style seeding via
# DuckDB's sample clause keeps findings reproducible.

from __future__ import annotations


def sample_rel(rel: str, rows: int, seed: int) -> str:
    """Wrap a relation in a seeded reservoir sample of `rows` rows."""
    if rows <= 0:
        raise ValueError("sample size must be positive")
    return f"(SELECT * FROM {rel} USING SAMPLE {int(rows)} ROWS (reservoir, {int(seed)}))"
