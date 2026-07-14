# 2026-07-13 (P3): The scan — "point it at data, get back what's interesting."
#
# Pipeline: sample (seeded, reproducible) -> classify columns -> test every pair with the
# type-appropriate test -> Benjamini-Hochberg across the whole family (this is what stops the
# decoy columns from surfacing) -> if a target is given, run the regression ladder, the
# multivariate model, and diagnostics -> PCA over the numeric columns.
#
# Everything comes back as ranked Findings with plain-English headlines. Language is strictly
# associational ("moves with", "differs across"), never causal — the tool cannot know causes, and
# saying otherwise would be the single most damaging thing it could do.

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from prospectra.core.mining.finding import Finding
from prospectra.core.sampling import sample_rel
from prospectra.core.stats.columns import ColumnRoles, classify
from prospectra.core.stats.diagnostics import Diagnostics, diagnose
from prospectra.core.stats.fdr import benjamini_hochberg
from prospectra.core.stats.multivariate import MultiFit, fit_multivariate
from prospectra.core.stats.pairs import PairTest, all_pairs
from prospectra.core.stats.pca import PCAResult, run_pca
from prospectra.core.stats.regression import Fit, best_fits

logger = logging.getLogger(__name__)

DEFAULT_MAX_ROWS = 50_000
DEFAULT_SEED = 42
DEFAULT_ALPHA = 0.05


@dataclass(frozen=True)
class ScanResult:
    dataset: str
    target: str | None
    n_rows: int  # rows in the full relation
    n_analyzed: int  # rows actually used (after sampling)
    sampled: bool
    seed: int
    alpha: float
    roles: ColumnRoles
    tests_run: int
    findings: list[Finding] = field(default_factory=list)  # significant, ranked
    rejected: list[Finding] = field(default_factory=list)  # failed FDR — kept for honesty
    drivers: list[Fit] = field(default_factory=list)  # regression ladder, ranked by adj R²
    model: MultiFit | None = None
    diagnostics: Diagnostics | None = None
    pca: PCAResult | None = None
    frame: pd.DataFrame | None = None  # the analyzed sample, for charts

    @property
    def summary(self) -> str:
        parts = [
            f"{self.tests_run} relationship test(s) on {self.n_analyzed:,} rows",
            f"{len(self.findings)} passed FDR control at q<={self.alpha}",
        ]
        if self.sampled:
            parts.append(f"sampled from {self.n_rows:,} rows (seed {self.seed})")
        return " · ".join(parts)


def scan_relation(
    cursor: duckdb.DuckDBPyConnection,
    rel: str,
    *,
    target: str | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    seed: int = DEFAULT_SEED,
    alpha: float = DEFAULT_ALPHA,
    dataset_name: str = "dataset",
) -> ScanResult:
    """Mine a relation (view name or parenthesized subquery) for relationships."""
    row = cursor.execute(f"SELECT count(*) FROM {rel}").fetchone()
    total = int(row[0]) if row else 0
    sampled = total > max_rows
    source = sample_rel(rel, max_rows, seed) if sampled else rel
    frame = cursor.execute(f"SELECT * FROM {source}").df()

    roles = classify(frame)
    if target is not None and target not in (*roles.numeric, *roles.categorical):
        reason = roles.excluded.get(target, "not a column of this dataset")
        raise ValueError(f"Cannot use {target!r} as the target: {reason}")

    tests = all_pairs(frame, roles.numeric, roles.categorical)
    q_values, rejected_flags = benjamini_hochberg([t.p_value for t in tests], alpha=alpha)

    findings: list[Finding] = []
    rejected: list[Finding] = []
    for test, q_value, significant in zip(tests, q_values, rejected_flags, strict=True):
        finding = _pair_finding(test, q_value)
        (findings if significant else rejected).append(finding)
    findings.sort(key=lambda f: f.effect, reverse=True)
    rejected.sort(key=lambda f: f.q_value)

    drivers: list[Fit] = []
    model: MultiFit | None = None
    diagnostics: Diagnostics | None = None
    if target is not None:
        if target in roles.numeric:
            drivers = best_fits(frame, target, roles.numeric, roles.categorical)
            findings.extend(_driver_findings(target, drivers))
            model = fit_multivariate(frame, target, roles.numeric, roles.categorical)
            if model is not None:
                findings.append(_model_finding(model))
                diagnostics = _diagnose_model(frame, target, model)
        else:
            logger.info(
                "Target %r is categorical — the regression ladder needs a numeric target; "
                "reporting group differences only.",
                target,
            )

    pca = run_pca(frame, roles.numeric)

    return ScanResult(
        dataset=dataset_name,
        target=target,
        n_rows=total,
        n_analyzed=len(frame),
        sampled=sampled,
        seed=seed,
        alpha=alpha,
        roles=roles,
        tests_run=len(tests),
        findings=findings,
        rejected=rejected,
        drivers=drivers,
        model=model,
        diagnostics=diagnostics,
        pca=pca,
        frame=frame,
    )


# -- finding construction -------------------------------------------------------------------


def _pair_finding(test: PairTest, q_value: float) -> Finding:
    payload: dict[str, Any] = {
        "test": test.test,
        "statistic": test.statistic,
        "kind": test.kind,
        "direction": test.direction,
        **test.detail,
    }
    if test.kind == "num-num":
        # "tends to" — associational by construction. Never "causes".
        verb = "rise" if test.direction == "positive" else "fall"
        headline = (
            f"When {test.a} goes up, {test.b} tends to {verb} "
            f"(r = {test.statistic:+.2f}, so {test.a} tracks "
            f"{test.detail.get('r_squared', 0.0):.0%} of the variation in {test.b})."
        )
        title = f"{test.a} ↔ {test.b}"
        kind = "correlation"
    elif test.kind == "num-cat":
        headline = (
            f"Average {test.a} differs across {test.b} groups "
            f"(the grouping accounts for {test.effect:.0%} of the variation in {test.a})."
        )
        title = f"{test.a} by {test.b}"
        kind = "group-difference"
    else:
        headline = (
            f"{test.a} and {test.b} are not independent — knowing one tells you something about "
            f"the other (Cramér's V = {test.effect:.2f})."
        )
        title = f"{test.a} ↔ {test.b}"
        kind = "correlation"

    return Finding(
        kind=kind,
        title=title,
        headline=headline,
        columns=[test.a, test.b],
        effect=test.effect,
        effect_name=test.effect_name,
        p_value=test.p_value,
        q_value=q_value,
        n=test.n,
        payload=payload,
    )


def _driver_findings(target: str, drivers: list[Fit]) -> list[Finding]:
    # The ladder is its own family of tests, so it gets its own BH correction — reusing the raw
    # p-value as a q-value would overstate significance exactly where the user is most likely to
    # act on it.
    q_values, _rejected = benjamini_hochberg([f.p_value for f in drivers])
    q_by_predictor = {f.predictor: q for f, q in zip(drivers, q_values, strict=True)}

    findings: list[Finding] = []
    for fit in drivers:
        if not np.isfinite(fit.adj_r2) or fit.adj_r2 <= 0.01:
            continue  # explains essentially nothing — not a finding
        shape = {
            "linear": "a straight-line relationship",
            "log-x": "a curved relationship (diminishing returns)",
            "log-y": "an exponential relationship",
            "log-log": "a proportional (elasticity) relationship",
            "quadratic": "a curved relationship that bends",
            "categorical": "different levels shifting the average",
        }[fit.form]
        headline = (
            f"{fit.predictor} explains {fit.adj_r2:.0%} of {target} on its own "
            f"({shape}; adjusted R² = {fit.adj_r2:.3f})."
        )
        findings.append(
            Finding(
                kind="driver",
                title=f"{fit.predictor} → {target}",
                headline=headline,
                columns=[fit.predictor, target],
                effect=float(max(0.0, min(1.0, fit.adj_r2))),
                effect_name="adj R²",
                p_value=fit.p_value,
                q_value=q_by_predictor[fit.predictor],
                n=fit.n,
                payload={
                    "form": fit.form,
                    "equation": fit.equation,
                    "r2": fit.r2,
                    "adj_r2": fit.adj_r2,
                    "native_r2": fit.native_r2,
                    "direction": fit.direction,
                    "std_coefficient": fit.std_coefficient,
                    "coefficients": fit.coefficients,
                    "caveat": fit.caveat,
                },
            )
        )
    return findings


def _model_finding(model: MultiFit) -> Finding:
    ranked = sorted(model.std_coefficients.items(), key=lambda kv: abs(kv[1]), reverse=True)
    named = ", ".join(name for name, _ in ranked[:3])
    headline = (
        f"Together, {len(model.predictors)} variable(s) explain {model.adj_r2:.0%} of "
        f"{model.target} (adjusted R² = {model.adj_r2:.3f}). Strongest contributors: {named}."
    )
    return Finding(
        kind="model",
        title=f"Best model for {model.target}",
        headline=headline,
        columns=list(model.predictors),
        effect=float(max(0.0, min(1.0, model.adj_r2))),
        effect_name="adj R²",
        p_value=model.p_value,
        q_value=model.p_value,
        n=model.n,
        payload={
            "predictors": model.predictors,
            "r2": model.r2,
            "adj_r2": model.adj_r2,
            "coefficients": model.coefficients,
            "std_coefficients": model.std_coefficients,
            "p_values": model.p_values,
            "vif": model.vif,
            "lasso_dropped": model.lasso_dropped,
            "notes": model.notes,
        },
    )


def _diagnose_model(frame: pd.DataFrame, target: str, model: MultiFit) -> Diagnostics | None:
    from prospectra.core.stats.multivariate import _design

    candidates = [c for c in frame.columns if c != target]
    data = frame[[target, *candidates]].dropna()
    design = _design(data, candidates)
    columns = [c for c in model.predictors if c in design.columns]
    if not columns:
        return None
    return diagnose(data[target].to_numpy(dtype=float), design[columns].to_numpy(dtype=float))
