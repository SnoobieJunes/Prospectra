# 2026-07-13 (P3): The regression ladder — for a chosen target, fit several functional forms per
# predictor and rank what explains it.
#
# THE TRAP THIS MODULE EXISTS TO AVOID: R-squared from a model whose *response* was transformed
# (log-y, log-log) explains the variance of ln(y), not of y. Comparing that number against a
# raw-y model's R-squared and calling the bigger one "better" is simply wrong — it is comparing
# two different questions. So every fit here is also scored on the ORIGINAL y scale: predictions
# are back-transformed and R-squared recomputed against the real target. Ranking uses that
# comparable number (`adj_r2`), and the model's own native R-squared is reported alongside it
# (`native_r2`) so nothing is hidden.
#
# Back-transformed exp(fitted) is the *median* response, not the mean (log-normal retransformation
# bias), so `adj_r2` for log-response forms is a fair comparison metric rather than that model's
# own goodness-of-fit statistic. `caveat` says so on the fit itself.

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import statsmodels.api as sm

MIN_ROWS = 12
FORMS = ("linear", "log-x", "log-y", "log-log", "quadratic")


@dataclass(frozen=True)
class Fit:
    predictor: str
    form: str  # linear | log-x | log-y | log-log | quadratic | categorical
    equation: str  # human-readable, e.g. "sales ~ ln(temperature)"
    n: int
    k: int  # predictors excluding the intercept
    r2: float  # R-squared on the ORIGINAL target scale — comparable across forms
    adj_r2: float  # adjusted version of the above; the ranking key
    native_r2: float  # the fitted model's own R-squared (of ln(y) for log-response forms)
    p_value: float  # F-test for the model as a whole
    coefficients: dict[str, float] = field(default_factory=dict)
    std_coefficient: float | None = None  # standardized slope (numeric single-predictor fits)
    direction: str = ""  # "positive" | "negative" | ""
    caveat: str = ""


def _r2_original(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - float(np.mean(y_true))) ** 2))
    if ss_tot <= 0:
        return 0.0
    return 1.0 - ss_res / ss_tot  # may go negative: a fit worse than the mean


def _adjust(r2: float, n: int, k: int) -> float:
    if n - k - 1 <= 0:
        return float("nan")
    return 1.0 - (1.0 - r2) * (n - 1) / (n - k - 1)


def _fit_ols(
    y_model: np.ndarray,
    design: np.ndarray,
    names: list[str],
    y_true: np.ndarray,
    log_response: bool,
) -> tuple[float, float, float, dict[str, float]] | None:
    """Fit OLS and score it on the original target scale. Returns (native_r2, r2, p, coefs)."""
    exog = sm.add_constant(design, has_constant="add")
    try:
        model = sm.OLS(y_model, exog).fit()
    except (ValueError, np.linalg.LinAlgError):
        return None
    predicted = np.asarray(model.fittedvalues, dtype=float)
    if log_response:
        predicted = np.exp(predicted)  # back to the original scale
    if not np.all(np.isfinite(predicted)):
        return None
    coefs = {
        name: float(value) for name, value in zip(["intercept", *names], model.params, strict=True)
    }
    p_value = float(model.f_pvalue) if np.isfinite(model.f_pvalue) else 1.0
    return float(model.rsquared), _r2_original(y_true, predicted), p_value, coefs


def fit_numeric_forms(frame: pd.DataFrame, target: str, predictor: str) -> list[Fit]:
    """Fit every applicable form of `target ~ predictor` and score them comparably."""
    data = frame[[target, predictor]].dropna()
    if len(data) < MIN_ROWS:
        return []
    y = data[target].to_numpy(dtype=float)
    x = data[predictor].to_numpy(dtype=float)
    if float(np.std(x)) == 0 or float(np.std(y)) == 0:
        return []

    n = len(data)
    x_positive = bool(np.all(x > 0))
    y_positive = bool(np.all(y > 0))
    fits: list[Fit] = []

    plans: list[tuple[str, str, np.ndarray, list[str], bool, str]] = [
        ("linear", f"{target} ~ {predictor}", x.reshape(-1, 1), [predictor], False, ""),
    ]
    if x_positive:
        plans.append(
            (
                "log-x",
                f"{target} ~ ln({predictor})",
                np.log(x).reshape(-1, 1),
                [f"ln({predictor})"],
                False,
                "",
            )
        )
    if y_positive:
        plans.append(
            (
                "log-y",
                f"ln({target}) ~ {predictor}",
                x.reshape(-1, 1),
                [predictor],
                True,
                "R-squared measured after back-transforming to the original scale",
            )
        )
    if x_positive and y_positive:
        plans.append(
            (
                "log-log",
                f"ln({target}) ~ ln({predictor})",
                np.log(x).reshape(-1, 1),
                [f"ln({predictor})"],
                True,
                "R-squared measured after back-transforming to the original scale",
            )
        )
    plans.append(
        (
            "quadratic",
            f"{target} ~ {predictor} + {predictor}^2",
            np.column_stack([x, x**2]),
            [predictor, f"{predictor}^2"],
            False,
            "",
        )
    )

    for form, equation, design, names, log_response, caveat in plans:
        y_model = np.log(y) if log_response else y
        result = _fit_ols(y_model, design, names, y, log_response)
        if result is None:
            continue
        native_r2, r2, p_value, coefs = result
        k = design.shape[1]
        slope = coefs.get(names[0], 0.0)
        std_coef = None
        if k == 1:
            sd_x = float(np.std(design[:, 0]))
            sd_y = float(np.std(y_model))
            std_coef = slope * sd_x / sd_y if sd_y > 0 else None
        fits.append(
            Fit(
                predictor=predictor,
                form=form,
                equation=equation,
                n=n,
                k=k,
                r2=r2,
                adj_r2=_adjust(r2, n, k),
                native_r2=native_r2,
                p_value=p_value,
                coefficients=coefs,
                std_coefficient=std_coef,
                direction=("positive" if slope >= 0 else "negative") if k == 1 else "",
                caveat=caveat,
            )
        )
    return fits


def fit_categorical(frame: pd.DataFrame, target: str, predictor: str) -> Fit | None:
    """A categorical predictor enters as dummy variables — ANOVA wearing a regression hat."""
    data = frame[[target, predictor]].dropna()
    if len(data) < MIN_ROWS:
        return None
    y = data[target].to_numpy(dtype=float)
    dummies = pd.get_dummies(data[predictor].astype(str), drop_first=True, dtype=float)
    if dummies.empty or dummies.shape[1] == 0:
        return None
    design = dummies.to_numpy(dtype=float)
    result = _fit_ols(y, design, list(dummies.columns), y, log_response=False)
    if result is None:
        return None
    native_r2, r2, p_value, coefs = result
    k = design.shape[1]
    return Fit(
        predictor=predictor,
        form="categorical",
        equation=f"{target} ~ C({predictor})",
        n=len(data),
        k=k,
        r2=r2,
        adj_r2=_adjust(r2, len(data), k),
        native_r2=native_r2,
        p_value=p_value,
        coefficients=coefs,
        caveat=f"{k + 1} groups; each level shifts the average",
    )


def best_fits(
    frame: pd.DataFrame, target: str, numeric: list[str], categorical: list[str]
) -> list[Fit]:
    """One best fit per predictor (the form with the highest comparable adj R-squared),
    ranked strongest first."""
    best: list[Fit] = []
    for predictor in numeric:
        if predictor == target:
            continue
        fits = [f for f in fit_numeric_forms(frame, target, predictor) if np.isfinite(f.adj_r2)]
        if fits:
            best.append(max(fits, key=lambda f: f.adj_r2))
    for predictor in categorical:
        fit = fit_categorical(frame, target, predictor)
        if fit is not None and np.isfinite(fit.adj_r2):
            best.append(fit)
    return sorted(best, key=lambda f: f.adj_r2, reverse=True)
