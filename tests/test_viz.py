# 2026-07-14 (P5): Viz-layer tests — the chart model, its SQL, and dashboards in the project file.
#
# The behaviour these lock down is the honesty of the chart layer, not its looks:
#   * a top-N bar chart SAYS it is truncated (an unlabelled truncated chart is a misread waiting
#     to happen);
#   * a log scale that has to drop non-positive rows COUNTS and reports them, never silently
#     omits them;
#   * a spec survives the JSON round trip into a .prospectra file, or a saved dashboard is a lie.

from __future__ import annotations

import csv
from pathlib import Path

import duckdb
import pytest

from prospectra.core.project import ProjectStore
from prospectra.core.viz import (
    ChartSpec,
    Dashboard,
    build_sql,
    data_to_csv,
    fetch_chart_data,
)
from prospectra.example_data import write_csv


@pytest.fixture
def cursor(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    csv_path = write_csv(tmp_path / "ice_cream.csv", days=200, seed=42)
    con = duckdb.connect()
    con.execute(f"CREATE VIEW icecream AS SELECT * FROM read_csv_auto('{csv_path.as_posix()}')")
    return con


# -- the spec ------------------------------------------------------------------------------------


def test_spec_round_trips_through_json():
    spec = ChartSpec(
        mark="scatter",
        x="temperature_c",
        y="ice_cream_sales",
        color="day_of_week",
        y_scale="log",
        dataset="ice",
    )
    restored = ChartSpec.from_dict(spec.to_dict())
    assert restored == spec  # including the id: a saved tile must reopen as the same tile


def test_spec_rejects_a_future_schema():
    doc = ChartSpec(x="a", y="b").to_dict()
    doc["spec_schema"] = 99
    with pytest.raises(ValueError, match="newer than this app"):
        ChartSpec.from_dict(doc)


def test_spec_validation_asks_for_what_is_missing():
    with pytest.raises(ValueError, match="X shelf"):
        ChartSpec(mark="bar", agg="sum").validate()
    with pytest.raises(ValueError, match="Y shelf"):
        ChartSpec(mark="scatter", x="temperature_c").validate()
    ChartSpec(mark="bar", x="day_of_week", agg="count").validate()  # count needs no Y
    ChartSpec(mark="histogram", x="temperature_c").validate()  # nor does a histogram


def test_titles_are_written_for_humans():
    spec = ChartSpec(mark="bar", x="day_of_week", y="ice_cream_sales", agg="mean")
    assert spec.display_title == "mean of ice_cream_sales by day_of_week"
    assert ChartSpec(mark="histogram", x="temperature_c").display_title == (
        "Distribution of temperature_c"
    )


# -- the query -----------------------------------------------------------------------------------


def test_bar_chart_aggregates_in_the_database(cursor: duckdb.DuckDBPyConnection):
    spec = ChartSpec(mark="bar", x="day_of_week", y="ice_cream_sales", agg="mean")
    sql = build_sql(spec, "icecream")
    assert "avg(" in sql and "GROUP BY" in sql
    data = fetch_chart_data(cursor, spec, "icecream")
    assert len(data.x) == 7  # one bar per weekday
    assert data.series_names == [""]  # no colour column -> a single series, so no legend


def test_scatter_returns_raw_rows(cursor: duckdb.DuckDBPyConnection):
    spec = ChartSpec(mark="scatter", x="temperature_c", y="ice_cream_sales")
    data = fetch_chart_data(cursor, spec, "icecream")
    assert len(data.x) == len(data.y) > 100
    assert not data.notes  # nothing was dropped or truncated, so nothing to confess


def test_colour_column_splits_the_data_into_named_series(cursor: duckdb.DuckDBPyConnection):
    spec = ChartSpec(
        mark="bar", x="day_of_week", y="ice_cream_sales", color="school_out", agg="sum"
    )
    data = fetch_chart_data(cursor, spec, "icecream")
    assert set(data.series_names) == {"0", "1"}  # school_out is a 0/1 flag in the tutorial data


def test_top_n_truncation_is_reported(cursor: duckdb.DuckDBPyConnection):
    """A bar chart showing 5 of 200 dates must say so — silence here is a lie by omission."""
    spec = ChartSpec(mark="bar", x="date", y="ice_cream_sales", agg="sum", limit=5)
    data = fetch_chart_data(cursor, spec, "icecream")
    assert len(data.x) == 5
    assert data.truncated is True
    assert any("top 5 of" in note for note in data.notes)


def test_log_scale_drops_non_positive_values_and_counts_them():
    con = duckdb.connect()
    con.execute(
        "CREATE VIEW t AS SELECT * FROM (VALUES ('a', 10.0), ('b', 0.0), ('c', -5.0)) "
        "AS v(name, value)"
    )
    spec = ChartSpec(mark="bar", x="name", y="value", agg="sum", y_scale="log")
    data = fetch_chart_data(con, spec, "t")
    assert data.y == [10.0]  # zero and the negative cannot exist on a log axis
    assert any("2 point(s) at or below zero" in note for note in data.notes)
    con.close()


def test_column_names_with_quotes_do_not_break_the_sql():
    con = duckdb.connect()
    con.execute('CREATE VIEW t AS SELECT 1 AS "we""ird", 2.0 AS v')
    spec = ChartSpec(mark="bar", x='we"ird', y="v", agg="sum")
    data = fetch_chart_data(con, spec, "t")
    assert data.y == [2.0]
    con.close()


# -- export --------------------------------------------------------------------------------------


def test_csv_export_carries_the_numbers_and_the_caveats(
    cursor: duckdb.DuckDBPyConnection, tmp_path: Path
):
    spec = ChartSpec(mark="bar", x="date", y="ice_cream_sales", agg="sum", limit=3)
    data = fetch_chart_data(cursor, spec, "icecream")
    path = data_to_csv(data, tmp_path / "chart.csv")
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    assert rows[0][0].startswith("#")  # the truncation note travels with the numbers
    assert rows[1] == ["date", "sum of ice_cream_sales"]
    assert len(rows) == 5  # note + header + 3 bars


# -- dashboards ----------------------------------------------------------------------------------


def test_dashboard_lays_tiles_out_in_a_grid():
    dashboard = Dashboard(name="Sales")
    for i in range(3):
        dashboard.add(
            ChartSpec(mark="bar", x="day_of_week", y="ice_cream_sales", title=f"chart {i}")
        )
    assert [(t.row, t.column) for t in dashboard.tiles] == [(0, 0), (0, 1), (1, 0)]


def test_removing_a_tile_closes_the_gap():
    dashboard = Dashboard()
    specs = [ChartSpec(mark="bar", x="day_of_week", y="ice_cream_sales") for _ in range(3)]
    for spec in specs:
        dashboard.add(spec)
    dashboard.remove(specs[0].id)
    assert [(t.row, t.column) for t in dashboard.tiles] == [(0, 0), (0, 1)]


def test_dashboard_survives_the_project_file(tmp_path: Path):
    dashboard = Dashboard(name="Ice cream")
    dashboard.add(
        ChartSpec(mark="scatter", x="temperature_c", y="ice_cream_sales", dataset="ice_cream_sales")
    )
    store = ProjectStore.create(tmp_path / "p.prospectra")
    try:
        record = store.save_dashboard(dashboard.name, dashboard.to_doc(), dashboard.id)
        reopened = Dashboard.from_doc(store.list_dashboards()[0].layout)
        assert reopened.name == "Ice cream"
        assert reopened.tiles[0].spec.x == "temperature_c"
        assert reopened.datasets() == ["ice_cream_sales"]

        # Re-saving the same dashboard updates it in place rather than making a copy.
        dashboard.name = "Renamed"
        store.save_dashboard(dashboard.name, dashboard.to_doc(), dashboard.id)
        records = store.list_dashboards()
        assert len(records) == 1
        assert records[0].name == "Renamed"
        assert records[0].id == record.id
    finally:
        store.close()


def test_project_staging_dir_is_a_sibling_of_the_project(tmp_path: Path):
    store = ProjectStore.create(tmp_path / "trip.prospectra")
    try:
        assert store.staging_dir == tmp_path / "trip_files"
        assert store.staging_dir.is_dir()
    finally:
        store.close()
