# 2026-07-13 (P2): Union — any number of inputs, matched BY NAME (Tableau union semantics:
# heterogeneous column sets align by column name, missing columns become NULL).

from __future__ import annotations

from prospectra.core.flow.node import Node, register


@register
class UnionNode(Node):
    type_name = "union"
    display_name = "Union"
    category = "combine"
    min_inputs = 2
    max_inputs = -1  # unlimited

    def compile(self, inputs: list[str]) -> str:
        selects = [f"SELECT * FROM {name}" for name in inputs]
        return "\n  UNION ALL BY NAME\n  ".join(selects)
