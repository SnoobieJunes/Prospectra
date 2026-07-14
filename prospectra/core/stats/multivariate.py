# 2026-07-13 (P3): The multi-predictor model — "which variables together explain the target?"
#
# Selection is forward stepwise on BIC, NOT on adjusted R-squared. That choice was forced by a
# test failure worth remembering: with n≈1100, adjusted R-squared's penalty ((n-1)/(n-k-1)) is so
# weak that a pure-noise column (competitor_promo, a decoy in the tutorial dataset) improved it
# fractionally and got admitted into the model with a standardized beta of -0.016. BIC penalises
# each added parameter by ~ln(n) — about 7 here — so a predictor must actually pay for itself.
# The noise columns are now correctly left out.
#
# A LassoCV cross-check follows: predictors that shrink to zero under L1 are flagged, because a
# variable that survives only one of the two methods deserves suspicion. Reports standardized
# coefficients (comparable across units) and VIF (multicollinearity — with correlated predictors
# like ad_spend and website_visits, individual coefficients get unstable and the user must be
# told, not quietly misled).

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.linear_model import LassoCV
from sklearn.preprocessing import StandardScaler

MIN_ROWS = 20
MAX_PREDICTORS = 12


@dataclass(frozen=True)
class MultiFit:
    target: str
    predictors: list[str]
    n: int
    r2: float
    adj_r2: float
    p_value: float
    coefficients: dict[str, float]
    std_coefficients: dict[str, float]  # comparable across units — the "importance" ordering
    p_values: dict[str, float]
    vif: dict[str, float] = field(default_factory=dict)
    lasso_dropped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _design(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Numeric columns pass through; categoricals become dummy columns."""
    parts: list[pd.DataFrame] = []
    for name in columns:
        series = frame[name]
        if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
            parts.append(series.astype(float).to_frame(name))
        else:
            dummies = pd.get_dummies(series.astype(str), prefix=name, drop_first=True, dtype=float)
            if not dummies.empty:
                parts.append(dummies)
    if not parts:
        return pd.DataFrame(index=frame.index)
    return pd.concat(parts, axis=1)


def _bic(model: sm.regression.linear_model.RegressionResultsWrapper) -> float:
    """Bayesian Information Criterion — lower is better; penalises each parameter by ~ln(n)."""
    value = float(model.bic)
    return value if np.isfinite(value) else np.inf


def fit_multivariate(
    frame: pd.DataFrame, target: str, numeric: list[str], categorical: list[str]
) -> MultiFit | None:
    candidates = [c for c in numeric if c != target] + [c for c in categorical if c != target]
    if not candidates:
        return None
    data = frame[[target, *candidates]].dropna()
    if len(data) < MIN_ROWS:
        return None

    y = data[target].to_numpy(dtype=float)
    design = _design(data, candidates)
    if design.empty or design.shape[1] == 0:
        return None
    notes: list[str] = []

    # --- forward stepwise selection on BIC (lower is better) ------------------------------
    remaining = list(design.columns)
    chosen: list[str] = []
    try:
        intercept_only = sm.OLS(y, np.ones((len(y), 1))).fit()
        best_score = _bic(intercept_only)  # the model to beat: "just the average"
    except (ValueError, np.linalg.LinAlgError):
        return None

    while remaining and len(chosen) < MAX_PREDICTORS:
        scored: list[tuple[float, str]] = []
        for column in remaining:
            trial = sm.add_constant(
                design[[*chosen, column]].to_numpy(dtype=float), has_constant="add"
            )
            try:
                model = sm.OLS(y, trial).fit()
            except (ValueError, np.linalg.LinAlgError):
                continue
            scored.append((_bic(model), column))
        if not scored:
            break
        score, column = min(scored)
        if score >= best_score:  # this predictor does not pay for its parameter — stop
            break
        best_score = score
        chosen.append(column)
        remaining.remove(column)

    if not chosen:
        return None

    exog = sm.add_constant(design[chosen].to_numpy(dtype=float), has_constant="add")
    model = sm.OLS(y, exog).fit()
    names = ["intercept", *chosen]
    coefficients = {n: float(v) for n, v in zip(names, model.params, strict=True)}
    p_values = {n: float(v) for n, v in zip(names, model.pvalues, strict=True)}

    # --- standardized coefficients: same model on z-scored data --------------------------
    scaler = StandardScaler()
    x_std = scaler.fit_transform(design[chosen].to_numpy(dtype=float))
    y_std = (y - y.mean()) / (y.std() if y.std() > 0 else 1.0)
    std_model = sm.OLS(y_std, sm.add_constant(x_std, has_constant="add")).fit()
    std_coefficients = {
        name: float(value) for name, value in zip(chosen, std_model.params[1:], strict=True)
    }

    # --- VIF: how much each coefficient is inflated by its correlation with the others ----
    vif: dict[str, float] = {}
    if len(chosen) >= 2:
        from statsmodels.stats.outliers_influence import variance_inflation_factor

        matrix = sm.add_constant(design[chosen].to_numpy(dtype=float), has_constant="add")
        for i, name in enumerate(chosen, start=1):
            try:
                value = float(variance_inflation_factor(matrix, i))
            except (ValueError, ZeroDivisionError, np.linalg.LinAlgError):
                continue
            if np.isfinite(value):
                vif[name] = value
        worst = [n for n, v in vif.items() if v > 10]
        if worst:
            notes.append(
                "Predictors "
                + ", ".join(worst)
                + " are strongly correlated with the others (VIF > 10), so their individual "
                "coefficients are unstable — trust the model's overall fit, not their separate "
                "sizes."
            )

    # --- Lasso cross-check ----------------------------------------------------------------
    lasso_dropped: list[str] = []
    try:
        lasso = LassoCV(cv=5, random_state=0, max_iter=5000).fit(
            StandardScaler().fit_transform(design.to_numpy(dtype=float)), y
        )
        kept = {c for c, coef in zip(design.columns, lasso.coef_, strict=True) if abs(coef) > 1e-8}
        lasso_dropped = [c for c in chosen if c not in kept]
        if lasso_dropped:
            notes.append(
                "Lasso (a shrinkage method) would drop "
                + ", ".join(lasso_dropped)
                + " — treat those as weak evidence."
            )
    except (ValueError, np.linalg.LinAlgError):
        notes.append("Lasso cross-check could not run on this data.")

    return MultiFit(
        target=target,
        predictors=chosen,
        n=len(data),
        r2=float(model.rsquared),
        adj_r2=float(model.rsquared_adj),
        p_value=float(model.f_pvalue) if np.isfinite(model.f_pvalue) else 1.0,
        coefficients=coefficients,
        std_coefficients=std_coefficients,
        p_values=p_values,
        vif=vif,
        lasso_dropped=lasso_dropped,
        notes=notes,
    )
