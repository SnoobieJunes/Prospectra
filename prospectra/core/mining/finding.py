# 2026-07-13 (P3): A Finding is one surfaced result, in the user's language.
# Every finding carries its evidence (test, effect size, q-value, n) and its lineage (dataset,
# sample seed) so it can be reproduced exactly, and so the P4 hypothesis engine can ask the LLM
# "why might this be?" with the numbers attached. `headline` is deliberately non-causal:
# correlation is reported as association, never as cause.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Finding:
    kind: str  # "correlation" | "group-difference" | "driver" | "model" | "pca"
    title: str
    headline: str  # plain English, non-causal
    columns: list[str]
    effect: float  # 0..1 comparable strength
    effect_name: str
    p_value: float
    q_value: float  # FDR-adjusted; the honest significance number
    n: int
    payload: dict[str, Any] = field(default_factory=dict)  # test-specific detail for the UI

    @property
    def strength(self) -> str:
        e = abs(self.effect)
        if e >= 0.5:
            return "strong"
        if e >= 0.3:
            return "moderate"
        if e >= 0.1:
            return "weak"
        return "very weak"
