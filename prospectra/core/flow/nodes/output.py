# 2026-07-13 (P2): Output — materializes its input to CSV or Parquet. The node compiles to a
# pass-through SELECT; the runner wraps it in COPY so previewing an output shows its data.

from __future__ import annotations

from typing import ClassVar

from prospectra.core.flow.node import Node, ParamField, register


@register
class OutputNode(Node):
    type_name = "output"
    display_name = "Output"
    category = "output"
    params_schema: ClassVar = (
        ParamField("path", "Write to file", "path", help="Destination .csv or .parquet path"),
        ParamField("format", "Format", "choice", "csv", ("csv", "parquet")),
    )

    def validate(self) -> None:
        if not str(self.params.get("path", "")).strip():
            raise ValueError("set the output file path")

    def compile(self, inputs: list[str]) -> str:
        return f"SELECT * FROM {inputs[0]}"
