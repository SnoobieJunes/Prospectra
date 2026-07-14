# 2026-07-13 (P3): One-way analysis of variance — "does this numeric column differ across the
# groups of that category?" Reports F, p, and eta-squared (the share of the numeric column's
# variance explained by group membership), plus per-group means for the chart and the narrative.

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

MIN_GROUP_SIZE = 3


@dataclass(frozen=True)
class AnovaResult:
    value: str
    group: str
    f_statistic: float
    p_value: float
    eta_squared: float  # 0..1 share of variance explained by the grouping
    n: int
    k_groups: int
    group_means: dict[str, float]
    group_counts: dict[str, int]


def one_way_anova(frame: pd.DataFrame, value: str, group: str) -> AnovaResult | None:
    data = frame[[value, group]].dropna()
    if data.empty:
        return None
    grouped = [(str(name), g[value].to_numpy(dtype=float)) for name, g in data.groupby(group)]
    usable = [(name, values) for name, values in grouped if len(values) >= MIN_GROUP_SIZE]
    if len(usable) < 2:
        return None

    samples = [values for _name, values in usable]
    all_values = np.concatenate(samples)
    if float(np.std(all_values)) == 0:
        return None
    f_stat, p_value = stats.f_oneway(*samples)
    if not np.isfinite(f_stat):
        return None

    grand_mean = float(np.mean(all_values))
    ss_between = float(sum(len(v) * (float(np.mean(v)) - grand_mean) ** 2 for v in samples))
    ss_total = float(np.sum((all_values - grand_mean) ** 2))
    eta_squared = ss_between / ss_total if ss_total > 0 else 0.0

    return AnovaResult(
        value=value,
        group=group,
        f_statistic=float(f_stat),
        p_value=float(p_value),
        eta_squared=float(min(max(eta_squared, 0.0), 1.0)),
        n=len(all_values),
        k_groups=len(usable),
        group_means={name: float(np.mean(values)) for name, values in usable},
        group_counts={name: len(values) for name, values in usable},
    )
