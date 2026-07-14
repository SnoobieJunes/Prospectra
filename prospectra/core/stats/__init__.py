# 2026-07-13 (P3): Full statistics surface — profiling, column roles, pair tests, FDR, the
# regression ladder, multivariate model, diagnostics, ANOVA, and PCA.
# 2026-07-13 (P1): Statistics package — profiling only.
from prospectra.core.stats.anova import AnovaResult, one_way_anova
from prospectra.core.stats.columns import ColumnRoles, classify
from prospectra.core.stats.diagnostics import Diagnostics, diagnose
from prospectra.core.stats.fdr import benjamini_hochberg
from prospectra.core.stats.multivariate import MultiFit, fit_multivariate
from prospectra.core.stats.pairs import PairTest, all_pairs, test_pair
from prospectra.core.stats.pca import Component, PCAResult, run_pca
from prospectra.core.stats.profile import Bin, ColumnProfile, TableProfile, profile_relation
from prospectra.core.stats.regression import Fit, best_fits, fit_categorical, fit_numeric_forms

__all__ = [
    "AnovaResult",
    "Bin",
    "ColumnProfile",
    "ColumnRoles",
    "Component",
    "Diagnostics",
    "Fit",
    "MultiFit",
    "PCAResult",
    "PairTest",
    "TableProfile",
    "all_pairs",
    "benjamini_hochberg",
    "best_fits",
    "classify",
    "diagnose",
    "fit_categorical",
    "fit_multivariate",
    "fit_numeric_forms",
    "one_way_anova",
    "profile_relation",
    "run_pca",
    "test_pair",
]
