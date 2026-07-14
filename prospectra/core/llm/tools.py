# 2026-07-13 (P4): The tools the assistant is given. These are the ONLY way data can reach a
# model — the raw data is never pasted into a prompt.
#
# `aggregate` is deliberately structured rather than free-form SQL: the model names the group-by
# columns and picks metrics from a fixed list, and this code builds the SQL. That is what makes
# the AGGREGATES privacy level *provably* aggregate-only — there is no query shape the model can
# construct that returns an individual row. Free-form SQL exists only at SAMPLE_ROWS, and even
# then it runs in the sandbox behind the SELECT-only guard.

from __future__ import annotations

import json
import logging
from typing import Any

from prospectra.core.llm.base import ToolSpec
from prospectra.core.llm.privacy import PrivacyLevel
from prospectra.core.llm.sandbox import QuerySandbox
from prospectra.core.llm.sqlguard import MAX_ROWS, UnsafeSQLError, check_select, wrap_with_limit
from prospectra.core.mining import Finding
from prospectra.core.sqlutil import ident

logger = logging.getLogger(__name__)

METRICS = ("count", "sum", "avg", "min", "max", "median", "stddev")


class ToolError(Exception):
    """The tool could not run — the message goes back to the model so it can correct itself."""


class ToolBox:
    """Binds the tool implementations to one sandbox and one set of findings."""

    def __init__(
        self,
        sandbox: QuerySandbox,
        privacy: PrivacyLevel,
        findings: list[Finding] | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.privacy = privacy
        self.findings = findings or []

    # -- schemas ---------------------------------------------------------------------------

    def specs(self) -> list[ToolSpec]:
        """Only the tools this privacy level permits — the rest are never even mentioned."""
        return [spec for spec in _ALL_SPECS if self.privacy.allows(spec.name)]

    # -- dispatch --------------------------------------------------------------------------

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        if not self.privacy.allows(name):
            # Defence in depth: the tool was never offered, so a model asking for it is either
            # confused or probing. Tell it plainly rather than silently failing.
            raise ToolError(
                f"The tool {name!r} is not available at the current privacy level "
                f"({self.privacy.label}). The user would need to raise it."
            )
        handler = getattr(self, f"_{name}", None)
        if handler is None:
            raise ToolError(f"unknown tool {name!r}")
        return str(handler(**arguments))

    # -- implementations --------------------------------------------------------------------

    def _list_datasets(self) -> str:
        return json.dumps(
            [
                {"table": t.table, "rows_available": t.rows, "sampled": t.sampled}
                for t in self.sandbox.tables.values()
            ]
        )

    def _describe_dataset(self, table: str) -> str:
        schema = self.sandbox.schema()
        if table not in schema:
            raise ToolError(f"no table {table!r}; call list_datasets first")
        info = self.sandbox.tables[table]
        return json.dumps(
            {
                "table": table,
                "rows_available": info.rows,
                "sampled_from_larger_dataset": info.sampled,
                "columns": [{"name": n, "type": t} for n, t in schema[table]],
            }
        )

    def _column_stats(self, table: str, column: str) -> str:
        self._require_column(table, column)
        col = ident(column)
        row = self.sandbox.execute(
            f"SELECT count(*), count({col}), approx_count_distinct({col}) FROM {ident(table)}"
        )[1][0]
        total, non_null, distinct = _int(row[0]), _int(row[1]), _int(row[2])
        stats: dict[str, Any] = {
            "table": table,
            "column": column,
            "rows": total,
            "nulls": total - non_null,
            "distinct": distinct,
        }
        if self._is_numeric(table, column):
            values = self.sandbox.execute(
                f"SELECT min({col}), max({col}), avg({col}), stddev({col}), median({col}) "
                f"FROM {ident(table)}"
            )[1][0]
            stats |= {
                "min": _num(values[0]),
                "max": _num(values[1]),
                "mean": _num(values[2]),
                "stddev": _num(values[3]),
                "median": _num(values[4]),
            }
        else:
            top = self.sandbox.execute(
                f"SELECT CAST({col} AS VARCHAR), count(*) AS n FROM {ident(table)} "
                f"WHERE {col} IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT 10"
            )[1]
            # Category labels are aggregate-level information (a value plus its count), not rows.
            stats["top_values"] = [{"value": str(v), "count": _int(c)} for v, c in top]
        return json.dumps(stats)

    def _aggregate(
        self,
        table: str,
        metrics: list[dict[str, str]],
        group_by: list[str] | None = None,
        limit: int = 50,
    ) -> str:
        group_by = group_by or []
        for column in group_by:
            self._require_column(table, column)
        selects: list[str] = [ident(c) for c in group_by]
        for metric in metrics:
            func = str(metric.get("function", "")).lower()
            column = str(metric.get("column", ""))
            if func not in METRICS:
                raise ToolError(f"metric must be one of {', '.join(METRICS)} — got {func!r}")
            if func == "count" and column in ("", "*"):
                selects.append("count(*) AS count_rows")
                continue
            self._require_column(table, column)
            selects.append(f"{func}({ident(column)}) AS {ident(f'{func}_{column}')}")
        if not selects:
            raise ToolError("ask for at least one metric")

        sql = f"SELECT {', '.join(selects)} FROM {ident(table)}"
        if group_by:
            keys = ", ".join(ident(c) for c in group_by)
            sql += f" GROUP BY {keys} ORDER BY {keys}"
        sql += f" LIMIT {min(int(limit), 200)}"
        columns, rows = self.sandbox.execute(sql)
        return json.dumps({"columns": columns, "rows": [[_cell(v) for v in r] for r in rows]})

    def _run_sql(self, sql: str) -> str:
        try:
            checked = check_select(sql)
        except UnsafeSQLError as exc:
            raise ToolError(str(exc)) from exc
        columns, rows = self.sandbox.execute(wrap_with_limit(checked))
        return json.dumps(
            {
                "columns": columns,
                "rows": [[_cell(v) for v in r] for r in rows],
                "row_limit": MAX_ROWS,
            }
        )

    def _list_findings(self) -> str:
        return json.dumps(
            [
                {
                    "index": i,
                    "kind": f.kind,
                    "title": f.title,
                    "strength": f.strength,
                    "effect": round(f.effect, 4),
                    "effect_name": f.effect_name,
                    "q_value": f.q_value,
                }
                for i, f in enumerate(self.findings)
            ]
        )

    def _get_finding(self, index: int) -> str:
        try:
            finding = self.findings[int(index)]
        except (IndexError, ValueError) as exc:
            raise ToolError(f"no finding at index {index}; call list_findings first") from exc
        return json.dumps(
            {
                "kind": finding.kind,
                "title": finding.title,
                "headline": finding.headline,
                "columns": finding.columns,
                "effect": finding.effect,
                "effect_name": finding.effect_name,
                "p_value": finding.p_value,
                "q_value": finding.q_value,
                "n": finding.n,
                "detail": finding.payload,
            },
            default=str,
        )

    # -- helpers ------------------------------------------------------------------------------

    def _require_column(self, table: str, column: str) -> None:
        schema = self.sandbox.schema()
        if table not in schema:
            raise ToolError(f"no table {table!r}; call list_datasets first")
        names = [n for n, _t in schema[table]]
        if column not in names:
            raise ToolError(f"no column {column!r} in {table!r}. Columns: {', '.join(names)}")

    def _is_numeric(self, table: str, column: str) -> bool:
        dtype = dict(self.sandbox.schema()[table])[column].upper()
        return dtype.startswith(
            ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "FLOAT", "DOUBLE", "DECIMAL")
        )


def _num(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def _int(value: object) -> int:
    # DuckDB hands rows back as `object`; these columns are counts by construction.
    return int(value)  # type: ignore[call-overload,no-any-return]


def _cell(value: object) -> object:
    return value if isinstance(value, (int, float, bool, type(None))) else str(value)


_ALL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="list_datasets",
        description="List the tables the user has shared with you, with their row counts.",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    ToolSpec(
        name="describe_dataset",
        description="Column names and types for one table. Start here.",
        parameters={
            "type": "object",
            "properties": {"table": {"type": "string"}},
            "required": ["table"],
        },
    ),
    ToolSpec(
        name="column_stats",
        description=(
            "Summary statistics for one column: nulls, distinct count, and either "
            "min/max/mean/median/stddev (numeric) or the most common values with their counts "
            "(categorical)."
        ),
        parameters={
            "type": "object",
            "properties": {"table": {"type": "string"}, "column": {"type": "string"}},
            "required": ["table", "column"],
        },
    ),
    ToolSpec(
        name="aggregate",
        description=(
            "Grouped summary of a table. You choose group-by columns and metrics; results are "
            "always aggregates, never individual rows."
        ),
        parameters={
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "group_by": {"type": "array", "items": {"type": "string"}},
                "metrics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "function": {"type": "string", "enum": list(METRICS)},
                            "column": {"type": "string"},
                        },
                        "required": ["function"],
                    },
                },
                "limit": {"type": "integer"},
            },
            "required": ["table", "metrics"],
        },
    ),
    ToolSpec(
        name="run_sql",
        description=(
            "Run a read-only SELECT against the shared tables and see the rows it returns. "
            "One statement, SELECT only; results are capped."
        ),
        parameters={
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
        },
    ),
    ToolSpec(
        name="list_findings",
        description="The statistical findings from the user's last scan, strongest first.",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    ToolSpec(
        name="get_finding",
        description="Full detail for one finding, by its index from list_findings.",
        parameters={
            "type": "object",
            "properties": {"index": {"type": "integer"}},
            "required": ["index"],
        },
    ),
)
