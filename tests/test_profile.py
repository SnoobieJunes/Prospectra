# 2026-07-13 (P1): Profiler correctness — null counts, histograms that sum to the non-null count,
# categorical top values, and the sampled-profile flag for large relations.

import pytest

from prospectra.core.catalog import Catalog
from prospectra.core.stats import profile_relation


@pytest.fixture()
def catalog():
    cat = Catalog()
    yield cat
    cat.close()


def test_profile_numeric_and_categorical(catalog, tmp_path):
    f = tmp_path / "mix.csv"
    f.write_text(
        "n,cat\n1,a\n2,a\n3,b\n4,b\n5,b\n,c\n10,\n",  # one null n, one null cat
        encoding="utf-8",
    )
    (ds,) = catalog.open_file(f)
    profile = catalog.profile(ds.id)
    assert profile.row_count == 7
    assert not profile.sampled

    by_name = {c.name: c for c in profile.columns}
    n = by_name["n"]
    assert n.numeric and n.null_count == 1
    assert (n.minimum, n.maximum) == (1.0, 10.0)
    assert sum(b.count for b in n.bins) == 6  # histogram covers every non-null value

    cat = by_name["cat"]
    assert not cat.numeric and cat.null_count == 1
    assert {(b.label, b.count) for b in cat.top} == {("a", 2), ("b", 3), ("c", 1)}


def test_profile_constant_column(catalog, tmp_path):
    f = tmp_path / "const.csv"
    f.write_text("k\n7\n7\n7\n", encoding="utf-8")
    (ds,) = catalog.open_file(f)
    (col,) = catalog.profile(ds.id).columns
    assert col.minimum == col.maximum == 7.0
    assert [(b.label, b.count) for b in col.bins] == [("7", 3)]


def test_profile_samples_large_relations(catalog):
    cur = catalog.cursor()
    cur.execute("CREATE TABLE big AS SELECT range AS n FROM range(120000)")
    profile = profile_relation(cur, "big", max_rows=50_000)
    assert profile.row_count == 120_000
    assert profile.sampled and profile.sample_size == 50_000
    (col,) = profile.columns
    assert sum(b.count for b in col.bins) == 50_000  # profiled exactly the sample


def test_profile_on_example_dataset(catalog):
    from prospectra.example_data import write_csv

    path = write_csv("examples/ice_cream_sales.csv")  # regenerates deterministically (seed 42)
    datasets = catalog.open_file(path)
    profile = catalog.profile(datasets[0].id)
    by_name = {c.name: c for c in profile.columns}
    assert by_name["temperature_c"].numeric
    assert by_name["day_of_week"].top  # categorical with top values
    assert profile.row_count == 1095
