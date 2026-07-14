# 2026-07-13 (P2): Graph -> one DuckDB SQL statement. Every node in the target's ancestry becomes
# a CTE (deterministically named by topological order), so the whole prep pipeline executes as a
# single query DuckDB can optimize end-to-end — the plan's "compile to SQL" strategy.

from __future__ import annotations

from prospectra.core.flow.graph import FlowGraph


def compile_sql(graph: FlowGraph, target_id: str) -> str:
    graph.validate_ready(target_id)
    order = graph.topo_order(target_id)
    names = {node_id: f"n{i}" for i, node_id in enumerate(order)}
    ctes: list[str] = []
    for node_id in order:
        inst = graph.nodes[node_id]
        input_names = [names[src] for src in graph.inputs_of(node_id)]
        body = inst.node.compile(input_names)
        ctes.append(f"{names[node_id]} AS (\n  {body}\n)")
    return "WITH " + ",\n".join(ctes) + f"\nSELECT * FROM {names[target_id]}"
