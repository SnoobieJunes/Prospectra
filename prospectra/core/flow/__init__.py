# 2026-07-13 (P2): Flow engine — Tableau-Prep-style prep pipelines. Graph model, node contract,
# SQL compiler, and runner. Import `prospectra.core.flow.nodes` registers the built-in node set.
from prospectra.core.flow import nodes as _nodes  # noqa: F401  (registers built-ins on import)
from prospectra.core.flow.errors import FlowError, FlowGraphError, FlowRunError
from prospectra.core.flow.graph import FlowGraph
from prospectra.core.flow.node import NODE_TYPES, Node, ParamField
from prospectra.core.flow.runner import FlowRunner, OutputResult, PreviewResult

__all__ = [
    "NODE_TYPES",
    "FlowError",
    "FlowGraph",
    "FlowGraphError",
    "FlowRunError",
    "FlowRunner",
    "Node",
    "OutputResult",
    "ParamField",
    "PreviewResult",
]
