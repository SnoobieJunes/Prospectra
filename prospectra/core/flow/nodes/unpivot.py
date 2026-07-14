# 2026-07-13 (P2): Unpivot — wide to long, the inverse of Pivot, via DuckDB's UNPIVOT table
# expression.

from __future__ import annotations

from typing import ClassVar

from prospectra.core.flow.node import Node, ParamField, register
from prospectra.core.sqlutil import ident


@register
class UnpivotNode(Node):
    type_name = "unpivot"
    display_name = "Unpivot (wide → long)"
    category = "transform"
    params_schema: ClassVar = (
        ParamField("columns", "Columns to fold (comma list)", "columns"),
        ParamField("name_to", "Name column", "string", "name"),
        ParamField("value_to", "Value column", "string", "value"),
    )

    def validate(self) -> None:
        if not str(self.params.get("columns", "")).strip():
            raise ValueError("list the columns to fold")

    def compile(self, inputs: list[str]) -> str:
        cols = ", ".join(
            ident(c.strip()) for c in str(self.params["columns"]).split(",") if c.strip()
        )
        name_to = ident(str(self.params.get("name_to", "name")).strip() or "name")
        value_to = ident(str(self.params.get("value_to", "value")).strip() or "value")
        return f"SELECT * FROM (UNPIVOT {inputs[0]} ON {cols} INTO NAME {name_to} VALUE {value_to})"
