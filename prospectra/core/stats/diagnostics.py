# 2026-07-13 (P3): Regression diagnostics — the "how much should I trust this?" traffic light.
# A high R-squared from a model whose assumptions are violated is a trap, so every reported model
# gets checked for: residual normality (Shapiro-Wilk, or Jarque-Bera above 5000 rows where
# Shapiro rejects essentially everything), heteroscedasticity (Breusch-Pagan), and influential
# outliers (Cook's distance). The verdict is plain English, not a p-value the user must decode.

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.diagnostic import het_breuschpagan

SHAPIRO_LIMIT = 5000


@dataclass(frozen=True)
class Diagnostics:
    verdict: str  # "good" | "caution" | "poor"
    normality_test: str
    normality_p: float | None
    homoscedasticity_p: float | None
    influential_points: int
    residuals: list[float] = field(default_factory=list)
    fitted: list[float] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def diagnose(y: np.ndarray, design: np.ndarray) -> Diagnostics | None:
    """Fit y ~ design and check the assumptions behind its R-squared."""
    exog = sm.add_constant(np.asarray(design, dtype=float), has_constant="add")
    try:
        model = sm.OLS(np.asarray(y, dtype=float), exog).fit()
    except (ValueError, np.linalg.LinAlgError):
        return None

    residuals = np.asarray(model.resid, dtype=float)
    fitted = np.asarray(model.fittedvalues, dtype=float)
    notes: list[str] = []
    problems = 0

    if len(residuals) <= SHAPIRO_LIMIT:
        normality_test = "Shapiro-Wilk"
        normality_p = float(stats.shapiro(residuals).pvalue)
    else:
        # Shapiro flags trivial deviations once n is large; Jarque-Bera is the honest choice here.
        normality_test = "Jarque-Bera"
        normality_p = float(stats.jarque_bera(residuals).pvalue)
    if normality_p < 0.05:
        problems += 1
        notes.append(
            "Residuals are not normally distributed, so the p-values and confidence intervals "
            "are approximate. The R-squared itself is still meaningful."
        )

    try:
        _lm, homoscedasticity_p, _f, _fp = het_breuschpagan(residuals, exog)
        homoscedasticity_p = float(homoscedasticity_p)
    except (ValueError, np.linalg.LinAlgError):
        homoscedasticity_p = None
    if homoscedasticity_p is not None and homoscedasticity_p < 0.05:
        problems += 1
        notes.append(
            "The spread of the errors changes across the range (heteroscedasticity) — the fit is "
            "more reliable in some parts of the data than others. A log transform often helps."
        )

    influential = 0
    try:
        cooks = model.get_influence().cooks_distance[0]
        threshold = 4.0 / len(residuals)
        influential = int(np.sum(cooks > threshold))
    except (ValueError, np.linalg.LinAlgError, ZeroDivisionError):
        pass
    share = influential / len(residuals) if len(residuals) else 0.0
    if share > 0.05:
        problems += 1
        notes.append(
            f"{influential} points ({share:.0%}) have outsized influence on the fit — a handful of "
            "rows may be driving this relationship."
        )

    verdict = "good" if problems == 0 else ("caution" if problems == 1 else "poor")
    if verdict == "good":
        notes.append("The model's assumptions hold up: this fit can be read at face value.")

    return Diagnostics(
        verdict=verdict,
        normality_test=normality_test,
        normality_p=normality_p,
        homoscedasticity_p=homoscedasticity_p,
        influential_points=influential,
        residuals=[float(v) for v in residuals],
        fitted=[float(v) for v in fitted],
        notes=notes,
    )
