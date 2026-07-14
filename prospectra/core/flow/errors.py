# 2026-07-13 (P2): Flow errors carry the offending node id so the canvas can point at the node
# instead of showing a bare SQL error.

from __future__ import annotations


class FlowError(Exception):
    """Base class for flow problems."""


class FlowGraphError(FlowError):
    """Structural problem (cycle, bad port, missing input)."""


class FlowRunError(FlowError):
    """Execution problem, attributed to a node."""

    def __init__(self, node_id: str, message: str) -> None:
        super().__init__(message)
        self.node_id = node_id
