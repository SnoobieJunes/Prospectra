# 2026-07-14 (P5): ChartSpec -> DuckDB SQL -> ChartData. The chart's data is computed in the
# database, not in Python: a bar chart of a 10M-row table must not pull 10M rows into the GUI.
#
# Two honesty rules are enforced here, and both leave a note the UI must show:
#   * A log scale cannot show zero or negative values. Rather than silently dropping them (which
#     would make a chart quietly lie about its own data) the rows are dropped *and counted*, and the
#     count is reported in `ChartData.notes`.
#   * Top-N truncation on a categorical bar chart is stated ("showing the top 30 of 412"), never
#     implied — an unlabelled truncated bar chart is a misread waiting to happen.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import duckdb

from prospectra.core.sqlutil import ident
from prospectra.core.viz.spec import MAX_POINTS, ChartSpec

_AGG_SQL = {
    "sum": "sum({col})",
    "mean": "avg({col})",
    "median": "median({col})",
    "count": "count(*)",
    "min": "min({col})",
    "max": "max({col})",
}


@dataclass(frozen=True)
class ChartData:
    """Rendered-ready columns. `series` is parallel to x/y ("" when the chart has one series)."""

    spec: ChartSpec
    x: list[Any] = field(default_factory=list)
    y: list[float] = field(default_factory=list)
    series: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # shown under the chart; never suppressed
    truncated: bool = False

    @property
    def series_names(self) -> list[str]:
        """Distinct series in first-seen order — the order hues are assigned in."""
        seen: list[str] = []
        for name in self.series:
            if name not in seen:
                seen.append(name)
        return seen

    def rows(self) -> list[tuple[Any, ...]]:
        if self.spec.color:
            return list(zip(self.x, self.series, self.y, strict=True))
        return list(zip(self.x, self.y, strict=True))

    def header(self) -> list[str]:
        if self.spec.color:
            return [self.spec.x, self.spec.color, self.spec.y_label]
        return [self.spec.x, self.spec.y_label]


def _log_filter(spec: ChartSpec) -> str:
    """WHERE clauses a log scale requires (log of a non-positive number does not exist)."""
    clauses: list[str] = []
    if spec.x_scale == "log" and spec.mark in ("scatter", "histogram"):
        clauses.append(f"{ident(spec.x)} > 0")
    if spec.y_scale == "log" and spec.y and spec.mark in ("scatter",):
        clauses.append(f"{ident(spec.y)} > 0")
    return " AND ".join(clauses)


def build_sql(spec: ChartSpec, relation: str) -> str:
    """The SELECT that produces this chart's data. `relation` is a view name or (subquery)."""
    spec.validate()
    x = ident(spec.x)

    if spec.mark == "histogram":
        conditions = [f"{x} IS NOT NULL"]
        log_where = _log_filter(spec)
        if log_where:
            conditions.append(log_where)
        return (
            f"SELECT {x} AS x FROM {relation} WHERE {' AND '.join(conditions)} LIMIT {MAX_POINTS}"
        )

    if not spec.aggregating:  # scatter / box: raw rows, capped
        y = ident(spec.y)
        parts = [f"{x} AS x", f"{y} AS y"]
        if spec.color:
            parts.append(f"CAST({ident(spec.color)} AS VARCHAR) AS series")
        conditions = [f"{x} IS NOT NULL", f"{y} IS NOT NULL"]
        log_where = _log_filter(spec)
        if log_where:
            conditions.append(log_where)
        return (
            f"SELECT {', '.join(parts)} FROM {relation} "
            f"WHERE {' AND '.join(conditions)} LIMIT {MAX_POINTS}"
        )

    # bar / line: aggregate in the database
    value = _AGG_SQL[spec.agg].format(col=ident(spec.y) if spec.y else "*")
    group = [x]
    parts = [f"{x} AS x"]
    if spec.color:
        series = f"CAST({ident(spec.color)} AS VARCHAR)"
        parts.append(f"{series} AS series")
        group.append(series)
    parts.append(f"{value} AS y")
    order = "y DESC" if spec.mark == "bar" else "x"
    return (
        f"SELECT {', '.join(parts)} FROM {relation} WHERE {x} IS NOT NULL "
        f"GROUP BY {', '.join(group)} ORDER BY {order} LIMIT {int(spec.limit)}"
    )


def _group_count_sql(spec: ChartSpec, relation: str) -> str:
    x = ident(spec.x)
    group = [x]
    if spec.color:
        group.append(f"CAST({ident(spec.color)} AS VARCHAR)")
    return (
        f"SELECT count(*) FROM (SELECT 1 FROM {relation} WHERE {x} IS NOT NULL "
        f"GROUP BY {', '.join(group)})"
    )


def fetch_chart_data(
    cursor: duckdb.DuckDBPyConnection, spec: ChartSpec, relation: str
) -> ChartData:
    """Run the chart's query and return its data, with every honesty note attached."""
    spec.validate()
    notes: list[str] = []

    if spec.mark == "histogram":
        rows = cursor.execute(build_sql(spec, relation)).fetchall()
        values = [float(r[0]) for r in rows]
        return ChartData(spec=spec, x=values, y=[], series=[], notes=notes)

    rows = cursor.execute(build_sql(spec, relation)).fetchall()
    if spec.color:
        xs = [r[0] for r in rows]
        series = [str(r[1]) for r in rows]
        ys = [float(r[2]) for r in rows]
    else:
        xs = [r[0] for r in rows]
        series = ["" for _ in rows]
        ys = [float(r[1]) for r in rows]

    truncated = False
    if spec.aggregating:
        total_row = cursor.execute(_group_count_sql(spec, relation)).fetchone()
        total = int(total_row[0]) if total_row else len(rows)
        if total > len(rows):
            truncated = True
            notes.append(
                f"Showing the top {len(rows)} of {total:,} {spec.x} values, ranked by "
                f"{spec.y_label}."
            )
    elif len(rows) == MAX_POINTS:
        truncated = True
        notes.append(f"Showing {MAX_POINTS:,} rows — the chart is drawn on a capped sample.")

    if spec.y_scale == "log":
        keep = [i for i, value in enumerate(ys) if value > 0]
        dropped = len(ys) - len(keep)
        if dropped:
            notes.append(
                f"{dropped:,} point(s) at or below zero are not shown — a log scale cannot "
                "display them."
            )
            xs = [xs[i] for i in keep]
            series = [series[i] for i in keep]
            ys = [ys[i] for i in keep]

    return ChartData(spec=spec, x=xs, y=ys, series=series, notes=notes, truncated=truncated)
