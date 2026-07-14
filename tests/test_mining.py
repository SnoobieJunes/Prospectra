# 2026-07-13 (P3): The P3 acceptance criterion — point the scan at the tutorial dataset, whose
# ground truth is known by construction (see prospectra/example_data.py), and require it to
# surface the planted drivers, reject the decoys via FDR, and never claim causation.

import pytest

from prospectra.core.catalog import Catalog
from prospectra.core.mining import save_scan, scan_relation
from prospectra.core.project import ProjectStore
from prospectra.example_data import write_csv

# Ground truth planted in the generator:
#   ice_cream_sales = 40 + 9.5*temperature + 120*school_out + 0.6*ad_spend + noise
#   website_visits  = 200 + 3.5*ad_spend + noise
# Decoys (pure noise, must be rejected): lottery_numbers, competitor_promo
DRIVERS = {"temperature_c", "school_out", "ad_spend"}
DECOYS = {"lottery_numbers", "competitor_promo"}


@pytest.fixture(scope="module")
def scan(tmp_path_factory):
    path = write_csv(tmp_path_factory.mktemp("data") / "ice.csv")
    catalog = Catalog()
    (dataset,) = catalog.open_file(path)
    result = scan_relation(
        catalog.cursor(), dataset.view_name, target="ice_cream_sales", dataset_name="ice"
    )
    yield result
    catalog.close()


def test_planted_drivers_rank_at_the_top(scan):
    ranked = [fit.predictor for fit in scan.drivers]
    assert ranked[0] == "temperature_c"  # the strongest planted effect
    assert ranked[1] == "school_out"
    # every decoy ranks below every planted driver
    for decoy in DECOYS:
        assert ranked.index(decoy) > max(ranked.index(d) for d in DRIVERS)


def test_reported_r2_is_sane_and_adjusted_is_lower(scan):
    for fit in scan.drivers:
        assert -1.0 <= fit.adj_r2 <= 1.0
        assert fit.adj_r2 <= fit.r2 + 1e-12  # adjustment can only penalise
    temperature = next(f for f in scan.drivers if f.predictor == "temperature_c")
    assert temperature.adj_r2 > 0.6  # planted coefficient 9.5 over a wide seasonal range


def test_decoys_are_rejected_by_fdr(scan):
    surfaced = {c for finding in scan.findings for c in finding.columns}
    for decoy in DECOYS:
        assert decoy not in surfaced, f"{decoy} is pure noise and must not surface as a finding"
    rejected = {c for finding in scan.rejected for c in finding.columns}
    assert rejected >= DECOYS


def test_multivariate_model_recovers_the_planted_equation(scan):
    model = scan.model
    assert model is not None
    assert set(model.predictors) >= DRIVERS
    assert model.adj_r2 > 0.85
    # the true coefficients are positive, and temperature dominates school_out dominates ad_spend
    betas = model.std_coefficients
    assert betas["temperature_c"] > betas["school_out"] > betas["ad_spend"] > 0


def test_findings_never_claim_causation(scan):
    banned = ("causes", "caused by", "because of", "drives up", "leads to")
    for finding in scan.findings:
        lowered = finding.headline.lower()
        for phrase in banned:
            assert phrase not in lowered, f"causal language in: {finding.headline}"


def test_confounded_column_surfaces_as_association_not_driver(scan):
    """humidity_pct has no causal link to sales — it is anti-correlated with temperature. The
    tool should surface it (it IS associated) without ranking it above the real drivers."""
    ranked = [fit.predictor for fit in scan.drivers]
    assert ranked.index("humidity_pct") > ranked.index("temperature_c")


def test_identifier_and_date_columns_are_excluded_with_a_reason(scan):
    assert "date" in scan.roles.excluded
    assert scan.roles.excluded["date"]  # a human-readable reason, not an empty string


def test_pca_runs_and_teaches(scan):
    assert scan.pca is not None
    assert scan.pca.components[0].explained > 0.2
    assert "never looked at your target" in scan.pca.narrative


def test_diagnostics_present(scan):
    assert scan.diagnostics is not None
    assert scan.diagnostics.verdict in ("good", "caution", "poor")
    assert scan.diagnostics.notes


def test_scan_is_reproducible_from_its_seed(tmp_path):
    path = write_csv(tmp_path / "ice.csv", days=400)
    catalog = Catalog()
    (dataset,) = catalog.open_file(path)
    kwargs = {"target": "ice_cream_sales", "max_rows": 200, "seed": 11}
    first = scan_relation(catalog.cursor(), dataset.view_name, **kwargs)
    second = scan_relation(catalog.cursor(), dataset.view_name, **kwargs)
    assert first.sampled and first.n_analyzed == 200
    assert [f.title for f in first.findings] == [f.title for f in second.findings]
    assert [round(f.effect, 12) for f in first.findings] == [
        round(f.effect, 12) for f in second.findings
    ]
    catalog.close()


def test_bad_target_is_reported(tmp_path):
    path = write_csv(tmp_path / "ice.csv", days=60)
    catalog = Catalog()
    (dataset,) = catalog.open_file(path)
    with pytest.raises(ValueError, match="date"):
        scan_relation(catalog.cursor(), dataset.view_name, target="date")
    catalog.close()


def test_findings_persist_to_the_project(tmp_path, scan):
    with ProjectStore.create(tmp_path / "p.prospectra") as store:
        count = save_scan(store, scan)
        assert count == len(scan.findings)
        rows = store._conn.execute(
            "SELECT kind, title, sample_seed, dataset_ref FROM findings"
        ).fetchall()
        assert len(rows) == count
        assert {r[3] for r in rows} == {"ice"}
        assert {r[2] for r in rows} == {scan.seed}  # lineage: reproducible from the seed
