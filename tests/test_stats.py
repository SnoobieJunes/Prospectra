# 2026-07-13 (P3): Golden tests for the statistics layer. Every number the app reports is checked
# against an independent reference implementation (statsmodels / scipy), because a mining tool
# that quietly reports a wrong R² is worse than no tool at all.

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
from scipy import stats as scipy_stats

from prospectra.core.stats import (
    benjamini_hochberg,
    classify,
    diagnose,
    fit_categorical,
    fit_multivariate,
    fit_numeric_forms,
    one_way_anova,
    run_pca,
)

# Aliased: pytest would otherwise collect the imported `test_pair` function as a test case.
from prospectra.core.stats import test_pair as run_pair_test


@pytest.fixture()
def rng():
    return np.random.default_rng(7)


# -- FDR ------------------------------------------------------------------------------------


def test_bh_matches_scipy_reference():
    p_values = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.5, 0.9]
    q_values, rejected = benjamini_hochberg(p_values, alpha=0.05)
    reference = scipy_stats.false_discovery_control(p_values, method="bh")
    assert np.allclose(q_values, reference, atol=1e-12)
    assert rejected == [q <= 0.05 for q in reference]


def test_bh_is_monotone_and_bounded():
    q_values, _ = benjamini_hochberg([0.9, 0.01, 0.5, 0.001])
    assert all(0.0 <= q <= 1.0 for q in q_values)
    # a smaller p-value can never receive a larger q-value
    pairs = sorted(zip([0.9, 0.01, 0.5, 0.001], q_values, strict=True))
    assert [q for _p, q in pairs] == sorted(q for _p, q in pairs)


def test_bh_rejects_pure_noise(rng):
    # 200 null tests -> uniform p-values -> BH should keep the false-discovery count near zero,
    # where an uncorrected alpha=0.05 would "find" ~10 relationships.
    p_values = list(rng.uniform(size=200))
    _q, rejected = benjamini_hochberg(p_values, alpha=0.05)
    assert sum(rejected) <= 1
    assert sum(p < 0.05 for p in p_values) >= 5  # the uncorrected test really would misfire


def test_bh_empty():
    assert benjamini_hochberg([]) == ([], [])


# -- pair tests -----------------------------------------------------------------------------


def test_pearson_matches_scipy(rng):
    frame = pd.DataFrame({"x": rng.normal(size=200)})
    frame["y"] = 2.5 * frame["x"] + rng.normal(size=200)
    result = run_pair_test(frame, "x", "y", True, True)
    reference = scipy_stats.pearsonr(frame["x"], frame["y"])
    assert result.test == "pearson"
    assert result.statistic == pytest.approx(reference.statistic, abs=1e-12)
    assert result.p_value == pytest.approx(reference.pvalue, abs=1e-12)
    assert result.effect == pytest.approx(abs(reference.statistic), abs=1e-12)
    assert result.direction == "positive"


def test_anova_matches_scipy(rng):
    frame = pd.DataFrame(
        {
            "g": ["a"] * 40 + ["b"] * 40 + ["c"] * 40,
            "v": np.concatenate([rng.normal(0, 1, 40), rng.normal(2, 1, 40), rng.normal(5, 1, 40)]),
        }
    )
    result = one_way_anova(frame, value="v", group="g")
    groups = [frame.loc[frame.g == name, "v"].to_numpy() for name in ("a", "b", "c")]
    reference = scipy_stats.f_oneway(*groups)
    assert result.f_statistic == pytest.approx(reference.statistic, rel=1e-10)
    assert result.p_value == pytest.approx(reference.pvalue, rel=1e-10)
    assert 0.0 <= result.eta_squared <= 1.0
    assert result.eta_squared > 0.5  # groups are well separated


def test_chi2_pair(rng):
    frame = pd.DataFrame({"a": ["x", "x", "y", "y"] * 30, "b": ["p", "q", "p", "q"] * 30})
    result = run_pair_test(frame, "a", "b", False, False)
    assert result.test == "chi2"
    assert result.p_value > 0.5  # independent by construction
    assert result.effect < 0.2


def test_pair_returns_none_on_constant_column():
    frame = pd.DataFrame({"x": [1.0] * 20, "y": list(range(20))})
    assert run_pair_test(frame, "x", "y", True, True) is None


# -- regression ladder ------------------------------------------------------------------------


def test_linear_fit_matches_statsmodels(rng):
    frame = pd.DataFrame({"x": rng.uniform(1, 50, 300)})
    frame["y"] = 3.0 + 1.7 * frame["x"] + rng.normal(0, 5, 300)

    fit = next(f for f in fit_numeric_forms(frame, "y", "x") if f.form == "linear")
    reference = sm.OLS(frame["y"], sm.add_constant(frame[["x"]])).fit()

    assert fit.r2 == pytest.approx(reference.rsquared, abs=1e-12)
    assert fit.adj_r2 == pytest.approx(reference.rsquared_adj, abs=1e-12)
    assert fit.native_r2 == pytest.approx(reference.rsquared, abs=1e-12)
    assert fit.p_value == pytest.approx(reference.f_pvalue, rel=1e-9)
    assert fit.coefficients["x"] == pytest.approx(reference.params["x"], abs=1e-12)
    assert fit.direction == "positive"


def test_log_response_r2_is_measured_on_the_original_scale(rng):
    """The trap: a log-y model's native R² describes ln(y), not y. The reported R² must be
    computed after back-transforming, or forms cannot be compared honestly."""
    x = rng.uniform(1, 10, 400)
    y = np.exp(0.35 * x + rng.normal(0, 0.15, 400))  # genuinely exponential
    frame = pd.DataFrame({"x": x, "y": y})

    log_y = next(f for f in fit_numeric_forms(frame, "y", "x") if f.form == "log-y")
    reference = sm.OLS(np.log(y), sm.add_constant(x)).fit()

    # native_r2 is the model's own (on ln y) and matches statsmodels…
    assert log_y.native_r2 == pytest.approx(reference.rsquared, abs=1e-12)
    # …while the reported r2 is measured against the real y, so it differs and is comparable.
    predicted = np.exp(reference.fittedvalues)
    expected = 1 - np.sum((y - predicted) ** 2) / np.sum((y - y.mean()) ** 2)
    assert log_y.r2 == pytest.approx(expected, abs=1e-12)
    assert log_y.r2 != pytest.approx(log_y.native_r2, abs=1e-6)


def test_ladder_picks_the_exponential_form_when_the_truth_is_exponential(rng):
    x = rng.uniform(1, 10, 400)
    y = np.exp(0.35 * x + rng.normal(0, 0.1, 400))
    frame = pd.DataFrame({"x": x, "y": y})
    fits = fit_numeric_forms(frame, "y", "x")
    best = max(fits, key=lambda f: f.adj_r2)
    assert best.form == "log-y"
    assert best.adj_r2 > 0.9


def test_ladder_picks_linear_when_the_truth_is_linear(rng):
    x = rng.uniform(1, 50, 400)
    y = 3 + 1.7 * x + rng.normal(0, 2, 400)
    frame = pd.DataFrame({"x": x, "y": y})
    best = max(fit_numeric_forms(frame, "y", "x"), key=lambda f: f.adj_r2)
    assert best.form in ("linear", "quadratic")  # quadratic may tie; both are straight-ish
    assert best.adj_r2 > 0.95


def test_log_forms_skipped_when_values_are_not_positive(rng):
    frame = pd.DataFrame({"x": rng.normal(size=100), "y": rng.normal(size=100)})
    forms = {f.form for f in fit_numeric_forms(frame, "y", "x")}
    assert forms == {"linear", "quadratic"}  # ln() of a negative is undefined, so those are gone


def test_categorical_fit_matches_statsmodels_anova(rng):
    frame = pd.DataFrame(
        {
            "g": ["a"] * 50 + ["b"] * 50 + ["c"] * 50,
            "y": np.concatenate([rng.normal(0, 1, 50), rng.normal(3, 1, 50), rng.normal(6, 1, 50)]),
        }
    )
    fit = fit_categorical(frame, "y", "g")
    dummies = pd.get_dummies(frame["g"], drop_first=True, dtype=float)
    reference = sm.OLS(frame["y"], sm.add_constant(dummies)).fit()
    assert fit.r2 == pytest.approx(reference.rsquared, abs=1e-12)
    assert fit.adj_r2 == pytest.approx(reference.rsquared_adj, abs=1e-12)
    assert fit.k == 2


# -- multivariate ----------------------------------------------------------------------------


def test_multivariate_recovers_the_real_predictors_and_ignores_noise(rng):
    n = 500
    frame = pd.DataFrame(
        {
            "a": rng.normal(size=n),
            "b": rng.normal(size=n),
            "noise1": rng.normal(size=n),
            "noise2": rng.normal(size=n),
        }
    )
    frame["y"] = 4 * frame["a"] - 2 * frame["b"] + rng.normal(0, 0.5, n)

    fit = fit_multivariate(frame, "y", ["a", "b", "noise1", "noise2"], [])
    assert set(fit.predictors) >= {"a", "b"}
    assert fit.adj_r2 > 0.95
    # standardized coefficients rank the true drivers correctly and by the right sign
    assert abs(fit.std_coefficients["a"]) > abs(fit.std_coefficients["b"])
    assert fit.std_coefficients["a"] > 0 and fit.std_coefficients["b"] < 0
    for noise in ("noise1", "noise2"):
        assert abs(fit.std_coefficients.get(noise, 0.0)) < 0.05


def test_multivariate_flags_multicollinearity(rng):
    n = 400
    a = rng.normal(size=n)
    frame = pd.DataFrame({"a": a, "twin": a + rng.normal(0, 0.01, n)})  # near-duplicate predictor
    frame["y"] = 3 * a + rng.normal(0, 0.5, n)
    fit = fit_multivariate(frame, "y", ["a", "twin"], [])
    if len(fit.predictors) >= 2:  # only if selection kept both
        assert max(fit.vif.values()) > 10
        assert any("correlated" in note for note in fit.notes)


# -- diagnostics -----------------------------------------------------------------------------


def test_diagnostics_pass_on_a_clean_model(rng):
    x = rng.normal(size=300)
    y = 2 * x + rng.normal(0, 1, 300)  # textbook OLS assumptions
    result = diagnose(y, x.reshape(-1, 1))
    assert result.verdict == "good"
    assert result.normality_p > 0.05
    assert len(result.residuals) == 300


def test_diagnostics_catch_heteroscedasticity(rng):
    x = rng.uniform(1, 10, 400)
    y = 2 * x + rng.normal(0, 1, 400) * x  # error grows with x
    result = diagnose(y, x.reshape(-1, 1))
    assert result.verdict in ("caution", "poor")
    assert result.homoscedasticity_p < 0.05
    assert any("spread" in note for note in result.notes)


def test_diagnostics_use_jarque_bera_on_large_samples(rng):
    x = rng.normal(size=6000)
    y = 2 * x + rng.normal(size=6000)
    result = diagnose(y, x.reshape(-1, 1))
    assert result.normality_test == "Jarque-Bera"  # Shapiro is useless above ~5000 rows


# -- PCA -------------------------------------------------------------------------------------


def test_pca_finds_the_planted_structure(rng):
    n = 400
    driver = rng.normal(size=n)
    other = rng.normal(size=n)
    frame = pd.DataFrame(
        {
            "a": driver + rng.normal(0, 0.1, n),  # a, b, c share one underlying factor
            "b": driver + rng.normal(0, 0.1, n),
            "c": driver + rng.normal(0, 0.1, n),
            "d": other + rng.normal(0, 0.1, n),  # d, e share a second, independent factor
            "e": other + rng.normal(0, 0.1, n),
        }
    )
    result = run_pca(frame, ["a", "b", "c", "d", "e"])
    assert result.components[0].explained > 0.4
    assert sum(c.explained for c in result.components[:2]) > 0.9  # two factors, two components
    pc1_drivers = {name for name, _ in result.components[0].drivers()}
    assert pc1_drivers <= {"a", "b", "c"} or pc1_drivers <= {"d", "e"}
    assert "never looked at your target" in result.narrative  # the unsupervised warning


def test_pca_needs_enough_columns():
    frame = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [1.0, 2.0, 3.0]})
    assert run_pca(frame, ["x", "y"]) is None


# -- column classification --------------------------------------------------------------------


def test_classify_excludes_ids_constants_and_dates():
    frame = pd.DataFrame(
        {
            "value": [1.0, 2.0, 3.0, 4.0],
            "flag": [True, False, True, False],
            "group": ["a", "b", "a", "b"],
            "row_id": ["r1", "r2", "r3", "r4"],  # unique per row -> identifier
            "constant": [7, 7, 7, 7],
            "when": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
        }
    )
    roles = classify(frame)
    assert set(roles.numeric) == {"value", "flag"}
    assert roles.categorical == ["group"]
    assert "identifier" in roles.excluded["row_id"]
    assert "constant" in roles.excluded["constant"]
    assert "date" in roles.excluded["when"]
