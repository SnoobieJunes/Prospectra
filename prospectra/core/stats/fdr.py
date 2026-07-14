# 2026-07-13 (P3): Benjamini-Hochberg false-discovery-rate control.
# Why this exists at all: a scan of 26 columns runs ~325 pair tests. At alpha=0.05 that yields
# ~16 "significant" results by pure chance — a false-positive machine. BH gives each test a
# q-value (the FDR you'd accept to call it real), so the decoy columns in a dataset get rejected
# instead of surfacing as trends. Every finding the app shows has passed this gate.

from __future__ import annotations

from collections.abc import Sequence


def benjamini_hochberg(
    p_values: Sequence[float], alpha: float = 0.05
) -> tuple[list[float], list[bool]]:
    """Return (q_values, rejected) aligned with the input order.

    q_values are BH-adjusted p-values (step-up, monotone-enforced). `rejected[i]` is True when
    q_values[i] <= alpha, which is the standard BH decision rule.
    """
    n = len(p_values)
    if n == 0:
        return [], []
    order = sorted(range(n), key=lambda i: p_values[i])
    q_sorted: list[float] = [0.0] * n
    running_min = 1.0
    # Step up from the largest p-value, enforcing monotonicity as we go.
    for rank in range(n, 0, -1):
        i = order[rank - 1]
        raw = p_values[i] * n / rank
        running_min = min(running_min, raw)
        q_sorted[rank - 1] = min(1.0, running_min)
    q_values = [0.0] * n
    for rank, i in enumerate(order):
        q_values[i] = q_sorted[rank]
    return q_values, [q <= alpha for q in q_values]
