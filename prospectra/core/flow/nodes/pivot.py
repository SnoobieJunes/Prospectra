# 2026-07-13 (P2): Pivot — long to wide (the "Pivot Quotas" step) via DuckDB's PIVOT table
# expression.

from __future__ import annotations

from typing import ClassVar

from prospectra.core.flow.node import Node, ParamField, register
from prospectra.core.sqlutil import ident


@register
class PivotNode(Node):
    type_name = "pivot"
    display_name = "Pivot (long → wide)"
    category = "transform"
    params_schema: ClassVar = (
        ParamField("on", "Spread values of column", "columns"),
        ParamField("using", "Aggregate", "expression", help="e.g. sum(quota)"),
        ParamField("group_by", "Group by (comma list, optional)", "columns"),
    )

    def validate(self) -> None:
        if not str(self.params.get("on", "")).strip():
            raise ValueError("choose the column to spread")
        if not str(self.params.get("using", "")).strip():
            raise ValueError("set the aggregate, e.g. sum(quota)")

    def compile(self, inputs: list[str]) -> str:
        on = ident(str(self.params["on"]).strip())
        using = str(self.params["using"]).strip()
        sql = f"PIVOT {inputs[0]} ON {on} USING {using}"
        group_cols = [
            c.strip() for c in str(self.params.get("group_by", "")).split(",") if c.strip()
        ]
        if group_cols:
            sql += " GROUP BY " + ", ".join(ident(c) for c in group_cols)
        return f"SELECT * FROM ({sql})"
