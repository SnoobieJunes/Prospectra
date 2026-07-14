# 2026-07-13 (P3): Pairwise relationship tests — the "A and X seem to move together" engine.
# The test is chosen by the pair's types, because using Pearson on a category is meaningless:
#   numeric x numeric      -> Pearson r (primary) + Spearman rho (monotone cross-check)
#   numeric x categorical  -> one-way ANOVA F, effect size eta-squared
#   categorical x categorical -> chi-square, effect size Cramer's V
# Exactly ONE p-value enters the FDR family per pair (Pearson for num-num), so the multiple-
# testing correction is not double-counting. Effect sizes are all on a 0..1 scale so findings
# from different tests can be ranked against each other.

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from prospectra.core.stats.anova import one_way_anova

MIN_ROWS = 8  # below this, nothing is worth reporting


@dataclass(frozen=True)
class PairTest:
    a: str
    b: str
    kind: str  # num-num | num-cat | cat-cat
    test: str  # pearson | anova | chi2
    statistic: float
    p_value: float
    effect: float  # |r| / eta-squared / Cramer's V — all 0..1
    effect_name: str
    n: int
    direction: str  # "positive" | "negative" | "" (non-directional tests)
    detail: dict[str, float]  # extras, e.g. spearman rho


def test_pair(
    frame: pd.DataFrame, a: str, b: str, a_numeric: bool, b_numeric: bool
) -> PairTest | None:
    """Run the type-appropriate test on the complete cases of columns a and b."""
    pair = frame[[a, b]].dropna()
    if len(pair) < MIN_ROWS:
        return None

    if a_numeric and b_numeric:
        return _num_num(pair, a, b)
    if a_numeric != b_numeric:
        num, cat = (a, b) if a_numeric else (b, a)
        return _num_cat(pair, num, cat)
    return _cat_cat(pair, a, b)


def _num_num(pair: pd.DataFrame, a: str, b: str) -> PairTest | None:
    x = pair[a].to_numpy(dtype=float)
    y = pair[b].to_numpy(dtype=float)
    if np.std(x) == 0 or np.std(y) == 0:
        return None  # no variance -> correlation undefined
    r, p = stats.pearsonr(x, y)
    rho, _rho_p = stats.spearmanr(x, y)
    return PairTest(
        a=a,
        b=b,
        kind="num-num",
        test="pearson",
        statistic=float(r),
        p_value=float(p),
        effect=abs(float(r)),
        effect_name="|r|",
        n=len(pair),
        direction="positive" if r >= 0 else "negative",
        detail={"spearman_rho": float(rho), "r_squared": float(r) ** 2},
    )


def _num_cat(pair: pd.DataFrame, num: str, cat: str) -> PairTest | None:
    result = one_way_anova(pair, value=num, group=cat)
    if result is None:
        return None
    return PairTest(
        a=num,
        b=cat,
        kind="num-cat",
        test="anova",
        statistic=result.f_statistic,
        p_value=result.p_value,
        effect=result.eta_squared,
        effect_name="eta-squared",
        n=result.n,
        direction="",
        detail={"groups": float(result.k_groups)},
    )


def _cat_cat(pair: pd.DataFrame, a: str, b: str) -> PairTest | None:
    table = pd.crosstab(pair[a], pair[b])
    if table.shape[0] < 2 or table.shape[1] < 2:
        return None
    chi2, p, _dof, _expected = stats.chi2_contingency(table)
    n = int(table.to_numpy().sum())
    min_dim = min(table.shape) - 1
    cramers_v = float(np.sqrt(chi2 / (n * min_dim))) if n and min_dim else 0.0
    return PairTest(
        a=a,
        b=b,
        kind="cat-cat",
        test="chi2",
        statistic=float(chi2),
        p_value=float(p),
        effect=min(cramers_v, 1.0),
        effect_name="Cramer's V",
        n=n,
        direction="",
        detail={},
    )


def all_pairs(frame: pd.DataFrame, numeric: list[str], categorical: list[str]) -> list[PairTest]:
    """Every unordered pair of usable columns, tested by type."""
    columns = [(c, True) for c in numeric] + [(c, False) for c in categorical]
    results: list[PairTest] = []
    for i in range(len(columns)):
        for j in range(i + 1, len(columns)):
            (a, a_num), (b, b_num) = columns[i], columns[j]
            result = test_pair(frame, a, b, a_num, b_num)
            if result is not None:
                results.append(result)
    return results
