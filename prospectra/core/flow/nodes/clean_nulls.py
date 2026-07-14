# 2026-07-13 (P2): Clean Nulls — the "Remove Nulls" step: drop rows with nulls in chosen columns,
# or fill them with a constant (numeric fills stay numeric; anything else becomes a string).

from __future__ import annotations

from typing import ClassVar

from prospectra.core.flow.node import Node, ParamField, register
from prospectra.core.sqlutil import ident, str_lit


def _fill_literal(raw: str) -> str:
    try:
        float(raw)
    except ValueError:
        return str_lit(raw)
    return raw


@register
class CleanNullsNode(Node):
    type_name = "clean_nulls"
    display_name = "Clean Nulls"
    category = "transform"
    params_schema: ClassVar = (
        ParamField("mode", "Action", "choice", "drop", ("drop", "fill")),
        ParamField("columns", "Columns (comma list)", "columns"),
        ParamField("fill_value", "Fill value (fill mode)", "string", "0"),
    )

    def validate(self) -> None:
        if not str(self.params.get("columns", "")).strip():
            raise ValueError("list the columns to clean")

    def compile(self, inputs: list[str]) -> str:
        src = inputs[0]
        cols = [c.strip() for c in str(self.params["columns"]).split(",") if c.strip()]
        if str(self.params.get("mode", "drop")) == "drop":
            condition = " AND ".join(f"{ident(c)} IS NOT NULL" for c in cols)
            return f"SELECT * FROM {src} WHERE {condition}"
        lit = _fill_literal(str(self.params.get("fill_value", "0")))
        replacements = ", ".join(f"COALESCE({ident(c)}, {lit}) AS {ident(c)}" for c in cols)
        return f"SELECT * REPLACE ({replacements}) FROM {src}"
