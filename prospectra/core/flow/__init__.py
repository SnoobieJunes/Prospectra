# 2026-07-13 (P2): Flow engine — Tableau-Prep-style prep pipelines. Graph model, node contract,
# SQL compiler, and runner. Import `prospectra.core.flow.nodes` registers the built-in node set.
# 2026-07-31 (P7): third-party node plugins now actually load — `load_external_nodes()` was
# documented (CONTRIBUTING.md, the `prospectra.flow_nodes` entry point) but had ZERO call sites,
# so the extension point did not function. Built-ins register first; a plugin cannot shadow them
# (load_external_nodes uses setdefault).
from prospectra.core.flow import nodes as _nodes  # noqa: F401  (registers built-ins on import)
from prospectra.core.flow.build import flow_from_columns, flow_readable, flow_with_mapping
from prospectra.core.flow.errors import FlowError, FlowGraphError, FlowRunError
from prospectra.core.flow.graph import FlowGraph
from prospectra.core.flow.node import NODE_TYPES, Node, ParamField, load_external_nodes
from prospectra.core.flow.runner import FlowRunner, OutputResult, PreviewResult, SelectPreview
from prospectra.core.flow.write import RowFailure, WriteReport

load_external_nodes()

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
    "RowFailure",
    "SelectPreview",
    "WriteReport",
    "flow_from_columns",
    "flow_readable",
    "flow_with_mapping",
    "load_external_nodes",
]
