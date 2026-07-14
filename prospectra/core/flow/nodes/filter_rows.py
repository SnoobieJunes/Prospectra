# 2026-07-13 (P2): Filter — keep rows matching a DuckDB SQL expression (the same expression
# language calculated fields use; Tableau's filter formulas map 1:1).

from __future__ import annotations

from typing import ClassVar

from prospectra.core.flow.node import Node, ParamField, register


@register
class FilterNode(Node):
    type_name = "filter"
    display_name = "Filter"
    category = "transform"
    params_schema: ClassVar = (
        ParamField(
            "expression",
            "Keep rows where",
            "expression",
            help="SQL expression, e.g. region = 'West' AND sales > 100",
        ),
    )

    def validate(self) -> None:
        if not str(self.params.get("expression", "")).strip():
            raise ValueError("set a filter expression")

    def compile(self, inputs: list[str]) -> str:
        return f"SELECT * FROM {inputs[0]} WHERE ({self.params['expression']})"
