# 2026-07-13 (P2): Aggregate — the "Roll Up Sales" step. Group-by columns plus SQL aggregate
# expressions (kept as expressions for P2; a visual agg builder layers on later).

from __future__ import annotations

from typing import ClassVar

from prospectra.core.flow.node import Node, ParamField, register
from prospectra.core.sqlutil import ident


@register
class AggregateNode(Node):
    type_name = "aggregate"
    display_name = "Aggregate"
    category = "transform"
    params_schema: ClassVar = (
        ParamField("group_by", "Group by (comma list, empty = whole table)", "columns"),
        ParamField(
            "aggregations",
            "Aggregations",
            "expression",
            help="e.g. sum(sales) AS total_sales, avg(price) AS avg_price",
        ),
    )

    def validate(self) -> None:
        if not str(self.params.get("aggregations", "")).strip():
            raise ValueError("set at least one aggregation")

    def compile(self, inputs: list[str]) -> str:
        group_cols = [
            c.strip() for c in str(self.params.get("group_by", "")).split(",") if c.strip()
        ]
        aggs = str(self.params["aggregations"]).strip()
        if not group_cols:
            return f"SELECT {aggs} FROM {inputs[0]}"
        idents = ", ".join(ident(c) for c in group_cols)
        return f"SELECT {idents}, {aggs} FROM {inputs[0]} GROUP BY {idents}"
