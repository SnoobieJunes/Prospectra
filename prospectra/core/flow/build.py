# 2026-07-14 (P5): Flow generators — graphs built by the app rather than drawn by hand.
#
# This is what makes the drag-and-drop promise honest. Dropping a few columns on "New dataset"
# could have been implemented as a hidden SELECT, but then the user would own a dataset with no
# record of where it came from. Instead the drop *writes a flow*: Input → Select(keep=…) → Output.
# The flow appears on the canvas, can be edited, re-run, saved with the project, and run headless —
# the derived dataset is reproducible rather than magic.

from __future__ import annotations

from pathlib import Path

from prospectra.core.connectors.files import _READERS
from prospectra.core.flow.graph import FlowGraph


def flow_readable(origin: str) -> bool:
    """Can a flow's Input node read this dataset's origin directly? (files DuckDB reads natively)"""
    path = Path(origin)
    return path.suffix.lower() in _READERS and path.is_file()


def flow_from_columns(
    source_path: Path | str, columns: list[str], out_path: Path | str
) -> FlowGraph:
    """Input(file) → Select(keep=columns) → Output(csv): the flow a column-drop stands for."""
    if not columns:
        raise ValueError("Pick at least one column")
    graph = FlowGraph()
    source = graph.add_node("input_file", {"path": str(source_path)}, pos=(40.0, 60.0))
    select = graph.add_node("select", {"keep": ", ".join(columns)}, pos=(260.0, 60.0))
    output = graph.add_node("output", {"path": str(out_path), "format": "csv"}, pos=(480.0, 60.0))
    graph.add_edge(source, select)
    graph.add_edge(select, output)
    return graph
