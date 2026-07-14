# 2026-07-14 (P5): Dashboards workspace tests — the builder, the tiles, and the round trip through
# a project file. The acceptance path P5 promises ("a chart on a dashboard") is exercised here with
# a real dataset in a real catalog: shelves are filled, a tile is added, its chart data is fetched
# and rendered, and the dashboard reopens with the tile intact.

from __future__ import annotations

from pathlib import Path

import pytest

from prospectra.core.catalog import Catalog
from prospectra.core.project import ProjectStore
from prospectra.core.viz import ChartSpec, Dashboard, fetch_chart_data
from prospectra.example_data import write_csv
from prospectra.ui.dashboards.dashboard_tab import DashboardTab
from prospectra.ui.widgets.spec_chart import CATEGORICAL_LIGHT, SpecChart


@pytest.fixture
def catalog(tmp_path: Path):
    csv_path = write_csv(tmp_path / "ice_cream.csv", days=90, seed=42)
    cat = Catalog()
    dataset = cat.open_file(csv_path)[0]
    yield cat, dataset
    cat.close()


def fill_shelves(tab: DashboardTab, dataset_id: str, x: tuple[str, str], y: tuple[str, str] | None):
    tab._x.set_column(dataset_id, x[0], x[1])
    if y is not None:
        tab._y.set_column(dataset_id, y[0], y[1])


# -- the builder ------------------------------------------------------------------------------


def test_marks_are_limited_to_what_the_dropped_columns_support(qtbot, catalog):
    """An impossible chart is unreachable, not merely an error: no scatter without two numbers."""
    cat, dataset = catalog
    tab = DashboardTab(cat)
    qtbot.addWidget(tab)

    fill_shelves(tab, dataset.id, ("day_of_week", "VARCHAR"), ("ice_cream_sales", "BIGINT"))
    marks = [tab._mark.itemData(i) for i in range(tab._mark.count())]
    assert "scatter" not in marks  # x is text
    assert "bar" in marks and "box" in marks

    fill_shelves(tab, dataset.id, ("temperature_c", "DOUBLE"), ("ice_cream_sales", "BIGINT"))
    marks = [tab._mark.itemData(i) for i in range(tab._mark.count())]
    assert "scatter" in marks and "histogram" in marks


def test_columns_from_two_datasets_are_refused_with_a_way_forward(qtbot, catalog):
    cat, dataset = catalog
    other = cat.derive_dataset(dataset.id, ["ad_spend"], "other")
    tab = DashboardTab(cat)
    qtbot.addWidget(tab)

    tab._x.set_column(dataset.id, "day_of_week", "VARCHAR")
    tab._y.set_column(other.id, "ad_spend", "DOUBLE")

    assert tab.current_spec() is None or not tab._add.isEnabled()
    assert "Join them in a Flow" in tab._builder_status.text()


def test_the_spec_the_builder_produces_matches_the_shelves(qtbot, catalog):
    cat, dataset = catalog
    tab = DashboardTab(cat)
    qtbot.addWidget(tab)
    fill_shelves(tab, dataset.id, ("day_of_week", "VARCHAR"), ("ice_cream_sales", "BIGINT"))
    tab._agg.setCurrentText("mean")

    spec = tab.current_spec()
    assert spec is not None
    assert spec.mark == "bar"
    assert (spec.x, spec.y, spec.agg) == ("day_of_week", "ice_cream_sales", "mean")
    # lineage: the tile can find its data again after a restart
    assert spec.dataset == dataset.name
    assert spec.origin == dataset.origin


# -- tiles ------------------------------------------------------------------------------------


def test_adding_a_chart_puts_a_tile_on_the_dashboard(qtbot, catalog):
    cat, dataset = catalog
    tab = DashboardTab(cat)
    qtbot.addWidget(tab)
    fill_shelves(tab, dataset.id, ("day_of_week", "VARCHAR"), ("ice_cream_sales", "BIGINT"))
    tab._add_tile()

    assert len(tab.dashboard.tiles) == 1
    tile_id = tab.dashboard.tiles[0].spec.id
    assert tile_id in tab._tiles

    # the tile's data lands via the thread pool
    qtbot.waitUntil(lambda: tab._tiles[tile_id]._data is not None, timeout=5000)
    data = tab._tiles[tile_id]._data
    assert len(data.x) == 7  # one bar per weekday


def test_adding_a_second_chart_does_not_blank_the_first(qtbot, catalog):
    """Regression: rebuilding the grid used to destroy every tile widget, so the first tile's
    in-flight data landed on a discarded widget and its chart stayed empty forever. Caught by
    looking at a screenshot of the running app, not by a test — hence this test."""
    cat, dataset = catalog
    tab = DashboardTab(cat)
    qtbot.addWidget(tab)

    fill_shelves(tab, dataset.id, ("day_of_week", "VARCHAR"), ("ice_cream_sales", "BIGINT"))
    tab._add_tile()
    first = tab.dashboard.tiles[0].spec.id

    fill_shelves(tab, dataset.id, ("temperature_c", "DOUBLE"), ("ice_cream_sales", "BIGINT"))
    marks = [tab._mark.itemData(i) for i in range(tab._mark.count())]
    tab._mark.setCurrentIndex(marks.index("scatter"))
    tab._add_tile()
    second = tab.dashboard.tiles[1].spec.id

    qtbot.waitUntil(
        lambda: tab._tiles[first]._data is not None and tab._tiles[second]._data is not None,
        timeout=5000,
    )
    assert tab._tiles[first]._data.spec.mark == "bar"  # the first chart still has its data
    assert tab._tiles[second]._data.spec.mark == "scatter"


def test_removing_a_tile_takes_it_off_the_grid(qtbot, catalog):
    cat, dataset = catalog
    tab = DashboardTab(cat)
    qtbot.addWidget(tab)
    fill_shelves(tab, dataset.id, ("day_of_week", "VARCHAR"), ("ice_cream_sales", "BIGINT"))
    tab._add_tile()
    spec_id = tab.dashboard.tiles[0].spec.id

    tab._remove_tile(spec_id)
    assert tab.dashboard.tiles == []
    assert tab._tiles == {}


def test_a_tile_whose_dataset_is_not_open_says_so_instead_of_drawing_nothing(qtbot, catalog):
    """An empty chart reads as "no data". A missing dataset must say it is missing."""
    cat, _dataset = catalog
    tab = DashboardTab(cat)
    qtbot.addWidget(tab)

    dashboard = Dashboard(name="stale")
    dashboard.add(
        ChartSpec(
            mark="bar",
            x="day_of_week",
            y="ice_cream_sales",
            dataset="a dataset nobody opened",
            origin="/somewhere/gone.csv",
        )
    )
    tab.load_dashboard(dashboard)

    tile = next(iter(tab._tiles.values()))
    assert "not open" in tile._status.text()
    assert "gone.csv" in tile._status.text()  # it names the file you need
    assert "Not open" in tab._status.text()


# -- persistence ------------------------------------------------------------------------------


def test_a_dashboard_saved_to_a_project_reopens_and_renders(qtbot, catalog, tmp_path: Path):
    cat, dataset = catalog
    tab = DashboardTab(cat)
    qtbot.addWidget(tab)
    fill_shelves(tab, dataset.id, ("temperature_c", "DOUBLE"), ("ice_cream_sales", "BIGINT"))
    marks = [tab._mark.itemData(i) for i in range(tab._mark.count())]
    tab._mark.setCurrentIndex(marks.index("scatter"))
    tab._add_tile()
    tab._rename("Ice cream")

    store = ProjectStore.create(tmp_path / "p.prospectra")
    try:
        store.save_dashboard(tab.dashboard.name, tab.dashboard.to_doc(), tab.dashboard.id)
        reopened = Dashboard.from_doc(store.list_dashboards()[0].layout)
    finally:
        store.close()

    fresh = DashboardTab(cat)
    qtbot.addWidget(fresh)
    fresh.load_dashboard(reopened)

    assert fresh.dashboard.name == "Ice cream"
    tile_id = fresh.dashboard.tiles[0].spec.id
    qtbot.waitUntil(lambda: fresh._tiles[tile_id]._data is not None, timeout=5000)
    assert fresh._tiles[tile_id]._data.spec.mark == "scatter"


# -- the renderer -----------------------------------------------------------------------------


def test_the_chart_renders_and_a_multi_series_chart_gets_a_legend(qtbot, catalog):
    cat, dataset = catalog
    chart = SpecChart()
    qtbot.addWidget(chart)

    spec = ChartSpec(
        mark="bar", x="day_of_week", y="ice_cream_sales", color="school_out", agg="sum"
    )
    data = fetch_chart_data(cat.cursor(), spec, cat.datasets[dataset.id].view_name)
    chart.render(data)

    assert chart.axes.get_legend() is not None  # two series -> identity is never colour-alone
    # titles sit left, per the dataviz method
    assert chart.axes.get_title(loc="left") == spec.display_title


def test_a_single_series_chart_has_no_legend_and_uses_the_sequential_hue(qtbot, catalog):
    cat, dataset = catalog
    chart = SpecChart()
    qtbot.addWidget(chart)

    spec = ChartSpec(mark="bar", x="day_of_week", y="ice_cream_sales", agg="sum")
    data = fetch_chart_data(cat.cursor(), spec, cat.datasets[dataset.id].view_name)
    chart.render(data)

    assert chart.axes.get_legend() is None  # one series: the title names it
    assert chart.series_color in (CATEGORICAL_LIGHT[0], "#3987e5")


def test_series_past_the_eighth_fold_into_other_rather_than_inventing_hues():
    names = [f"s{i}" for i in range(12)]
    folded = SpecChart._fold_others(names)
    assert folded["s7"] == "s7"
    assert folded["s8"] == "Other" and folded["s11"] == "Other"
    assert len(set(folded.values())) == 9  # 8 real series + Other


def test_chart_notes_are_drawn_on_the_figure_so_an_exported_png_keeps_them(qtbot, catalog):
    cat, dataset = catalog
    chart = SpecChart()
    qtbot.addWidget(chart)

    spec = ChartSpec(mark="bar", x="date", y="ice_cream_sales", agg="sum", limit=5)
    data = fetch_chart_data(cat.cursor(), spec, cat.datasets[dataset.id].view_name)
    assert data.notes
    chart.render(data)

    # the caption is the figure's supxlabel: constrained layout reserves room for it, so it
    # cannot land on top of the x-axis label (it did, in a rendered PNG, when it was figure text)
    assert "top 5 of" in chart.figure.get_supxlabel()

    # and a re-render with nothing to confess must not leave the old caption behind
    clean = ChartSpec(mark="bar", x="day_of_week", y="ice_cream_sales", agg="sum")
    chart.render(fetch_chart_data(cat.cursor(), clean, cat.datasets[dataset.id].view_name))
    assert chart.figure.get_supxlabel() == ""
