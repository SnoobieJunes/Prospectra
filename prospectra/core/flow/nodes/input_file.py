# 2026-07-13 (P2): Input node — reads CSV/TSV/text/JSON/Parquet straight from disk via DuckDB's
# readers (shares the suffix map with the P1 file connector). Excel/DB inputs join in a later
# phase once catalog datasets are draggable onto the canvas.

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from prospectra.core.connectors.files import _READERS
from prospectra.core.flow.node import Node, ParamField, register
from prospectra.core.sqlutil import path_lit


@register
class InputFileNode(Node):
    type_name = "input_file"
    display_name = "Input: File"
    category = "input"
    min_inputs = 0
    max_inputs = 0
    params_schema: ClassVar = (
        ParamField(
            "path",
            "File path",
            "path",
            help="CSV, TSV, text, JSON, JSONL or Parquet file",
        ),
    )

    def validate(self) -> None:
        raw = str(self.params.get("path", "")).strip()
        if not raw:
            raise ValueError("set a file path")
        if Path(raw).suffix.lower() not in _READERS:
            supported = ", ".join(sorted(_READERS))
            raise ValueError(f"unsupported file type (flows read: {supported})")

    def compile(self, inputs: list[str]) -> str:
        path = Path(str(self.params["path"]).strip())
        reader = _READERS[path.suffix.lower()]
        return f"SELECT * FROM {reader}({path_lit(path)})"
