# 2026-07-13 (P2): The flow graph — a validated DAG of node instances with ordered, ported edges
# (join needs a distinguishable left/right; union accepts many). Serializes to a versioned JSON
# doc stored in the .prospectra project, and every consumer (compiler, canvas, CLI) works off
# this one model.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from prospectra.core.flow.errors import FlowGraphError
from prospectra.core.flow.node import NODE_TYPES, Node

FLOW_SCHEMA = 1


@dataclass
class NodeInstance:
    id: str
    node: Node
    x: float = 0.0
    y: float = 0.0


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    port: int = 0  # join: 0 = left, 1 = right; other nodes use port 0


@dataclass
class FlowGraph:
    nodes: dict[str, NodeInstance] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    # -- construction -------------------------------------------------------------------

    def add_node(
        self,
        type_name: str,
        params: dict[str, Any] | None = None,
        pos: tuple[float, float] = (0.0, 0.0),
        node_id: str | None = None,
    ) -> str:
        if type_name not in NODE_TYPES:
            raise FlowGraphError(f"Unknown node type {type_name!r}")
        nid = node_id or uuid.uuid4().hex
        if nid in self.nodes:
            raise FlowGraphError(f"Duplicate node id {nid!r}")
        self.nodes[nid] = NodeInstance(
            id=nid, node=NODE_TYPES[type_name](params), x=pos[0], y=pos[1]
        )
        return nid

    def remove_node(self, node_id: str) -> None:
        self.nodes.pop(node_id, None)
        self.edges = [e for e in self.edges if node_id not in (e.src, e.dst)]

    def add_edge(self, src: str, dst: str, port: int = 0) -> None:
        if src not in self.nodes or dst not in self.nodes:
            raise FlowGraphError("Edge endpoints must exist")
        if src == dst:
            raise FlowGraphError("A node cannot feed itself")
        node = self.nodes[dst].node
        if node.max_inputs == 0:
            raise FlowGraphError(f"{node.display_name} takes no inputs")
        n_ports = 2 if type(node).max_inputs == 2 else 1
        if not (0 <= port < n_ports):
            raise FlowGraphError(f"{node.display_name} has no input port {port}")
        # capacity: multi-input port 0 is unlimited for union-style nodes; otherwise 1 per port
        existing = [e for e in self.edges if e.dst == dst and e.port == port]
        if node.max_inputs != -1 and existing:
            raise FlowGraphError(f"{node.display_name} input {port} is already connected")
        if any(e for e in self.edges if (e.src, e.dst, e.port) == (src, dst, port)):
            raise FlowGraphError("Edge already exists")
        if self._reaches(dst, src):
            raise FlowGraphError("That connection would create a cycle")
        self.edges.append(Edge(src, dst, port))

    def remove_edge(self, src: str, dst: str, port: int) -> None:
        self.edges = [e for e in self.edges if (e.src, e.dst, e.port) != (src, dst, port)]

    def _reaches(self, start: str, goal: str) -> bool:
        stack, seen = [start], set()
        while stack:
            current = stack.pop()
            if current == goal:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(e.dst for e in self.edges if e.src == current)
        return False

    # -- queries ------------------------------------------------------------------------

    def inputs_of(self, node_id: str) -> list[str]:
        """Input node ids ordered by (port, insertion order)."""
        incoming = [(e.port, i, e.src) for i, e in enumerate(self.edges) if e.dst == node_id]
        return [src for _port, _i, src in sorted(incoming)]

    def validate_ready(self, node_id: str) -> None:
        """Check `node_id` and all ancestors have enough inputs and usable params."""
        for nid in self.topo_order(node_id):
            inst = self.nodes[nid]
            n_in = len(self.inputs_of(nid))
            needed = inst.node.min_inputs
            if n_in < needed:
                raise FlowGraphError(
                    f"{inst.node.display_name} needs {needed} input(s), has {n_in}"
                )
            try:
                inst.node.validate()
            except ValueError as exc:
                raise FlowGraphError(f"{inst.node.display_name}: {exc}") from exc

    def topo_order(self, target: str | None = None) -> list[str]:
        """Topological order of the whole graph, or of `target`'s ancestry (incl. target)."""
        if target is not None:
            keep: set[str] = set()
            stack = [target]
            while stack:
                current = stack.pop()
                if current in keep:
                    continue
                keep.add(current)
                stack.extend(e.src for e in self.edges if e.dst == current)
        else:
            keep = set(self.nodes)
        order: list[str] = []
        placed: set[str] = set()
        remaining = {n for n in keep}
        while remaining:
            progress = False
            for nid in sorted(remaining):  # sorted -> deterministic CTE naming
                deps = {e.src for e in self.edges if e.dst == nid and e.src in keep}
                if deps <= placed:
                    order.append(nid)
                    placed.add(nid)
                    remaining.remove(nid)
                    progress = True
                    break
            if not progress:  # only reachable if invariants were bypassed
                raise FlowGraphError("Graph contains a cycle")
        return order

    def output_nodes(self) -> list[str]:
        return [nid for nid, inst in self.nodes.items() if inst.node.category == "output"]

    # -- persistence ----------------------------------------------------------------------

    def to_doc(self) -> dict[str, Any]:
        return {
            "flow_schema": FLOW_SCHEMA,
            "nodes": [
                {
                    "id": inst.id,
                    "type": type(inst.node).type_name,
                    "params": inst.node.params,
                    "x": inst.x,
                    "y": inst.y,
                }
                for inst in self.nodes.values()
            ],
            "edges": [[e.src, e.dst, e.port] for e in self.edges],
        }

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> FlowGraph:
        version = int(doc.get("flow_schema", 0))
        if version > FLOW_SCHEMA:
            raise FlowGraphError(
                f"Flow schema v{version} is newer than this app supports (v{FLOW_SCHEMA})"
            )
        graph = cls()
        for n in doc.get("nodes", []):
            graph.add_node(n["type"], n.get("params"), (n.get("x", 0), n.get("y", 0)), n["id"])
        for src, dst, port in doc.get("edges", []):
            graph.add_edge(src, dst, int(port))
        return graph
