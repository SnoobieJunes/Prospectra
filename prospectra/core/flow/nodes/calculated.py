# 2026-07-13 (P2): Calculated Field — adds a column from a DuckDB SQL expression (the
# "Create Calculated Field…" step in the sampleflow reference).

from __future__ import annotations

from typing import ClassVar

from prospectra.core.flow.node import Node, ParamField, register
from prospectra.core.sqlutil import ident


@register
class CalculatedFieldNode(Node):
    type_name = "calculated"
    display_name = "Calculated Field"
    category = "transform"
    params_schema: ClassVar = (
        ParamField("name", "New column name", "string"),
        ParamField(
            "expression",
            "Expression",
            "expression",
            help="SQL expression, e.g. ln(sales + 1) or price * quantity",
        ),
    )

    def validate(self) -> None:
        if not str(self.params.get("name", "")).strip():
            raise ValueError("name the new column")
        if not str(self.params.get("expression", "")).strip():
            raise ValueError("set an expression")

    def compile(self, inputs: list[str]) -> str:
        name = ident(str(self.params["name"]).strip())
        return f"SELECT *, ({self.params['expression']}) AS {name} FROM {inputs[0]}"
