# 2026-07-13 (P0): Guards the tutorial dataset's ground truth — planted relationships must be
# detectable and decoys must stay uncorrelated, or the P3 mining golden tests become meaningless.

import csv
import statistics

from prospectra.example_data import COLUMNS, generate_rows, write_csv


def _col(rows, key):
    return [float(r[key]) for r in rows]


def test_deterministic_for_fixed_seed():
    assert generate_rows(days=120) == generate_rows(days=120)


def test_different_seed_differs():
    assert generate_rows(days=120, seed=1) != generate_rows(days=120, seed=2)


def test_planted_relationships_hold():
    rows = generate_rows()  # default: 1095 days, seed 42
    sales = _col(rows, "ice_cream_sales")
    corr = statistics.correlation
    # Planted drivers must be clearly detectable…
    assert corr(sales, _col(rows, "temperature_c")) > 0.55
    assert corr(sales, _col(rows, "school_out")) > 0.25
    assert corr(_col(rows, "website_visits"), _col(rows, "ad_spend")) > 0.5
    # …and decoys must not correlate (FDR in P3 must reject these).
    assert abs(corr(sales, _col(rows, "lottery_numbers"))) < 0.12
    assert abs(corr(sales, _col(rows, "competitor_promo"))) < 0.12


def test_write_csv(tmp_path):
    path = write_csv(tmp_path / "sub" / "ice.csv", days=30)
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        body = list(reader)
    assert tuple(header) == COLUMNS
    assert len(body) == 30
