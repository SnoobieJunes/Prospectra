# 2026-07-13 (P3): Analyze workspace UI — a real scan of the tutorial dataset must populate the
# findings table, the driver ranking, the trust light, and the PCA narrative, offscreen.

import pytest

from prospectra.core.catalog import Catalog
from prospectra.example_data import write_csv
from prospectra.ui.analysis.analyze_tab import AnalyzeTab
from prospectra.ui.analysis.trust_light import TrustLight
from prospectra.ui.widgets.charts import Chart


@pytest.fixture()
def catalog_with_example(tmp_path):
    catalog = Catalog()
    catalog.open_file(write_csv(tmp_path / "ice.csv", days=400))
    yield catalog
    catalog.close()


def test_scan_populates_every_panel(qtbot, catalog_with_example):
    tab = AnalyzeTab(catalog_with_example)
    qtbot.addWidget(tab)
    tab.refresh_datasets()
    assert tab._dataset_picker.count() == 1

    index = tab._target_picker.findData("ice_cream_sales")
    assert index > 0  # the column list came from the catalog
    tab._target_picker.setCurrentIndex(index)

    tab._run_scan()
    qtbot.waitUntil(lambda: tab._scan is not None, timeout=30_000)

    # Relationships: FDR-controlled findings, top one selected and plotted
    assert tab._findings.rowCount() > 0
    assert "temperature_c" in tab._findings.item(0, 0).text()
    assert "not proof of cause" in tab._headline.text()

    # What drives…: temperature ranks first, model summary and trust light filled
    assert tab._drivers_table.item(0, 0).text() == "temperature_c"
    assert float(tab._drivers_table.item(0, 1).text()) > 0.6  # adj R²
    assert "adjusted R²" in tab._model_summary.toPlainText()
    assert "Trust:" in tab._trust._title.text()

    # PCA: narrative present, with the unsupervised warning, plus a loadings table
    assert "never looked at your target" in tab._pca_text.toPlainText()
    assert tab._loadings.rowCount() > 0


def test_scan_without_a_target_still_finds_relationships(qtbot, catalog_with_example):
    tab = AnalyzeTab(catalog_with_example)
    qtbot.addWidget(tab)
    tab.refresh_datasets()
    tab._target_picker.setCurrentIndex(0)  # "(no target …)"

    tab._run_scan()
    qtbot.waitUntil(lambda: tab._scan is not None, timeout=30_000)
    assert tab._findings.rowCount() > 0
    assert tab._drivers_table.rowCount() == 0  # nothing to explain -> no ladder
    assert "Pick a target" in tab._model_summary.toPlainText()


def test_trust_light_never_relies_on_colour_alone(qtbot):
    from prospectra.core.stats import Diagnostics

    light = TrustLight()
    qtbot.addWidget(light)
    light.set_diagnostics(
        Diagnostics(
            verdict="poor",
            normality_test="Shapiro-Wilk",
            normality_p=0.001,
            homoscedasticity_p=0.001,
            influential_points=12,
            notes=["errors fan out"],
        )
    )
    assert "POOR" in light._title.text()  # the word, not just the colour
    assert "errors fan out" in light._notes.text()


def test_charts_render_each_form(qtbot):
    chart = Chart()
    qtbot.addWidget(chart)
    chart.scatter_with_fit([1, 2, 3, 4], [2, 4, 5, 9], "x", "y")
    assert chart.axes.get_xlabel() == "x"
    chart.ranked_bars(["a", "b"], [0.8, 0.3], "drivers", "adj R²")
    assert len(chart.axes.patches) == 2
    chart.box_by_group({"a": [1, 2, 3], "b": [4, 5, 6]}, value="v", group="g")
    chart.scree([0.5, 0.3, 0.2], [0.5, 0.8, 1.0])
    chart.residuals([1.0, 2.0, 3.0], [0.1, -0.2, 0.05])
    assert chart.axes.get_ylabel().startswith("error")
