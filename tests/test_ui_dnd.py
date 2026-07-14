# 2026-07-14 (P5): Drag-and-drop backbone tests.
#
# These drive the *real* Qt drop path (QDropEvent onto the widget), not just the payload helpers —
# a MIME round-trip that no widget accepts would be a backbone that carries nothing. The
# column-drop → derived dataset → generated flow path is checked end to end, because the promise
# there is not "you get a table", it is "you get a table AND the flow that reproduces it".

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from prospectra.core.catalog import Catalog
from prospectra.core.flow import FlowRunner, flow_from_columns, flow_readable
from prospectra.core.mining import Finding
from prospectra.example_data import write_csv
from prospectra.ui.analysis.findings_table import FindingsTable
from prospectra.ui.dashboards.shelf import ColumnShelf, is_numeric
from prospectra.ui.dnd.mime import (
    MIME_COLUMN,
    ColumnPayload,
    DatasetPayload,
    FindingPayload,
    column_mime,
    dataset_mime,
    finding_mime,
    read_column,
    read_dataset,
    read_finding,
)
from prospectra.ui.docks.context_chips import ChipBar
from prospectra.ui.docks.sources import NewDatasetZone


@pytest.fixture
def catalog(tmp_path: Path):
    csv_path = write_csv(tmp_path / "ice_cream.csv", days=60, seed=42)
    cat = Catalog()
    yield cat, cat.open_file(csv_path)[0]
    cat.close()


def drop_on(widget, mime: QMimeData) -> None:
    """Deliver a real Qt drag-enter + drop to a widget, the way a mouse would."""
    position = QPoint(5, 5)
    enter = QDragEnterEvent(
        position,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.dragEnterEvent(enter)
    assert enter.isAccepted(), "the widget refused a payload it should accept"
    drop = QDropEvent(
        position,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.dropEvent(drop)


# -- the payloads ----------------------------------------------------------------------------


def test_column_payload_round_trips():
    payload = ColumnPayload(
        dataset_id="d1",
        dataset="ice_cream",
        origin="/tmp/ice.csv",
        columns=["temperature_c", "ad_spend"],
        dtypes=["DOUBLE", "DOUBLE"],
    )
    restored = read_column(column_mime(payload))
    assert restored == payload
    assert restored.column == "temperature_c"  # the lead column is what a single shelf takes


def test_dataset_and_finding_payloads_round_trip():
    dataset = DatasetPayload(dataset_id="d1", dataset="ice", origin="/tmp/ice.csv")
    assert read_dataset(dataset_mime(dataset)) == dataset

    finding = FindingPayload(
        kind="correlation",
        title="temperature_c ↔ ice_cream_sales",
        headline="When temperature_c goes up, ice_cream_sales tends to rise.",
        columns=["temperature_c", "ice_cream_sales"],
        effect=0.82,
        effect_name="|r|",
        q_value=1e-9,
    )
    assert read_finding(finding_mime(finding)) == finding


def test_payloads_carry_a_plain_text_fallback():
    mime = column_mime(ColumnPayload("d1", "ice", "/tmp/x.csv", ["temperature_c"], ["DOUBLE"]))
    assert mime.text() == "temperature_c"  # dropping into any text field still says something


def test_a_foreign_mime_type_is_not_mistaken_for_ours():
    mime = QMimeData()
    mime.setText("just text")
    assert read_column(mime) is None
    assert read_dataset(mime) is None
    assert read_finding(mime) is None


def test_corrupt_payload_is_refused_rather_than_crashing():
    mime = QMimeData()
    mime.setData(MIME_COLUMN, b"{not json")
    assert read_column(mime) is None


# -- chart shelves ---------------------------------------------------------------------------


def test_dropping_a_column_on_a_shelf_fills_it(qtbot):
    shelf = ColumnShelf("X")
    qtbot.addWidget(shelf)
    received: list[tuple[str, str, str]] = []
    shelf.changed.connect(lambda *args: received.append(args))

    drop_on(shelf, column_mime(ColumnPayload("d1", "ice", "/x.csv", ["day_of_week"], ["VARCHAR"])))

    assert shelf.column == "day_of_week"
    assert shelf.numeric is False
    assert received == [("d1", "day_of_week", "VARCHAR")]

    shelf.clear()
    assert shelf.column == ""


def test_shelf_knows_a_numeric_column_when_it_sees_one(qtbot):
    shelf = ColumnShelf("Y")
    qtbot.addWidget(shelf)
    drop_on(shelf, column_mime(ColumnPayload("d1", "ice", "/x.csv", ["ad_spend"], ["DOUBLE"])))
    assert shelf.numeric is True
    assert is_numeric("BIGINT") and not is_numeric("VARCHAR")


# -- chat context chips ----------------------------------------------------------------------


def test_dropping_a_column_on_the_chat_makes_a_context_chip(qtbot):
    bar = ChipBar()
    qtbot.addWidget(bar)
    payload = ColumnPayload("d1", "ice_cream", "/x.csv", ["temperature_c"], ["DOUBLE"])
    drop_on(bar, column_mime(payload))

    assert len(bar.chips) == 1
    assert bar.chips[0].kind == "column"
    preamble = bar.preamble()
    assert "temperature_c" in preamble and "ice_cream" in preamble


def test_dropping_a_finding_on_the_chat_carries_its_numbers(qtbot):
    bar = ChipBar()
    qtbot.addWidget(bar)
    finding = FindingPayload(
        kind="correlation",
        title="temperature_c ↔ ice_cream_sales",
        headline="They move together.",
        effect=0.82,
        effect_name="|r|",
        q_value=1e-9,
    )
    drop_on(bar, finding_mime(finding))
    context = bar.chips[0].context
    assert "0.82" in context and "They move together." in context


def test_chips_can_be_cleared(qtbot):
    bar = ChipBar()
    qtbot.addWidget(bar)
    drop_on(bar, dataset_mime(DatasetPayload("d1", "ice", "/x.csv")))
    assert bar.preamble() != ""
    bar.clear()
    assert bar.chips == []
    assert bar.preamble() == ""  # no chips -> the question travels alone


# -- findings table as a drag source ---------------------------------------------------------


def test_a_findings_row_drags_as_a_finding_payload(qtbot):
    table = FindingsTable(1, 1)
    qtbot.addWidget(table)
    finding = Finding(
        kind="correlation",
        title="temperature_c ↔ ice_cream_sales",
        headline="When temperature_c goes up, ice_cream_sales tends to rise.",
        columns=["temperature_c", "ice_cream_sales"],
        effect=0.82,
        effect_name="|r|",
        p_value=1e-12,
        q_value=1e-9,
        n=1000,
    )
    table.set_findings([finding])
    payload = read_finding(table.mimeData_for_row(0))
    assert payload is not None
    assert payload.title == finding.title
    assert payload.effect == pytest.approx(0.82)


# -- the New-dataset drop zone ---------------------------------------------------------------


def test_new_dataset_zone_emits_every_dropped_column(qtbot):
    zone = NewDatasetZone()
    qtbot.addWidget(zone)
    received: list[tuple[str, list[str]]] = []
    zone.columns_dropped.connect(lambda ds, cols: received.append((ds, cols)))

    payload = ColumnPayload(
        "d1", "ice", "/x.csv", ["temperature_c", "ad_spend"], ["DOUBLE", "DOUBLE"]
    )
    drop_on(zone, column_mime(payload))
    assert received == [("d1", ["temperature_c", "ad_spend"])]


def test_deriving_a_dataset_makes_a_real_view_of_just_those_columns(catalog):
    cat, dataset = catalog
    derived = cat.derive_dataset(dataset.id, ["temperature_c", "ice_cream_sales"], "two cols")
    assert [name for name, _dtype in cat.describe(derived.id)] == [
        "temperature_c",
        "ice_cream_sales",
    ]
    assert cat.count_rows(derived.id) == cat.count_rows(dataset.id)
    assert "derived from" in derived.origin  # lineage is recorded, not lost


def test_deriving_with_an_unknown_column_says_which_one(catalog):
    cat, dataset = catalog
    with pytest.raises(ValueError, match="no column"):
        cat.derive_dataset(dataset.id, ["nope"], "bad")


def test_the_generated_flow_actually_produces_the_derived_dataset(catalog, tmp_path: Path):
    """The drop's real promise: not just a table, but the flow that rebuilds it — and it runs."""
    _cat, dataset = catalog
    assert flow_readable(dataset.origin) is True

    out = tmp_path / "derived.csv"
    graph = flow_from_columns(dataset.origin, ["temperature_c", "ice_cream_sales"], out)
    results = FlowRunner().run(graph)

    assert len(results) == 1
    assert out.exists()
    header = out.read_text(encoding="utf-8").splitlines()[0]
    assert header == "temperature_c,ice_cream_sales"
    assert results[0].rows == 60


def test_a_dataset_a_flow_cannot_read_is_reported_rather_than_faked():
    assert flow_readable("db: sales.orders") is False  # a DB table is not a file an Input can read


# -- the flow canvas as a drop target ------------------------------------------------------


def test_dropping_a_dataset_on_the_canvas_makes_a_runnable_input_node(qtbot, catalog):
    """Closes the promise the P2 deviation made: catalog datasets become flow inputs by drag."""
    from prospectra.ui.flow.flow_tab import FlowTab

    _cat, dataset = catalog
    tab = FlowTab()
    qtbot.addWidget(tab)

    tab._view.dataset_dropped.emit(dataset.name, dataset.origin, 60.0, 40.0)

    assert len(tab.graph.nodes) == 1
    node = next(iter(tab.graph.nodes.values())).node
    assert type(node).type_name == "input_file"
    assert node.params["path"] == dataset.origin
    node.validate()  # the node the drop produced is valid, not a stub that fails on run


def test_a_dataset_a_flow_cannot_read_is_refused_on_the_canvas_with_a_reason(qtbot, catalog):
    from prospectra.ui.flow.flow_tab import FlowTab

    _cat, dataset = catalog
    tab = FlowTab()
    qtbot.addWidget(tab)

    mime = dataset_mime(DatasetPayload(dataset.id, "orders", "db: sales.orders"))
    drop_on(tab._view, mime)

    assert tab.graph.nodes == {}  # no node that would fail the moment it ran
    assert "reads files DuckDB opens natively" in tab._status.text()
