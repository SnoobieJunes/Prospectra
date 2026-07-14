# 2026-07-13 (P2): Sample — seeded reservoir sample, the plan's reproducibility hook: flows that
# feed the mining engine record their sample seed so findings can be recomputed exactly.

from __future__ import annotations

from typing import ClassVar

from prospectra.core.flow.node import Node, ParamField, register
from prospectra.core.sampling import sample_rel


@register
class SampleNode(Node):
    type_name = "sample"
    display_name = "Sample"
    category = "transform"
    params_schema: ClassVar = (
        ParamField("rows", "Rows", "int", 10_000),
        ParamField("seed", "Seed", "int", 42),
    )

    def validate(self) -> None:
        try:
            if int(self.params.get("rows", 0)) <= 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError("rows must be a positive integer") from exc

    def compile(self, inputs: list[str]) -> str:
        rows = int(self.params["rows"])
        seed = int(self.params.get("seed", 42))
        return f"SELECT * FROM {sample_rel(inputs[0], rows, seed)}"
