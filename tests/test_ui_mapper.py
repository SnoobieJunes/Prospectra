# 2026-07-31 (P7): The drag-and-drop mapper, driven through the REAL Qt drop path (the same
# drop_on helper the P5 backbone tests use) — a mapper whose drop targets only work in theory is
# a mapper that carries nothing. House style: private attrs, explicit seams.

from __future__ import annotations

import pytest

from prospectra.core.flow import FlowGraph, FlowRunner, flow_with_mapping
from prospectra.core.mapping import FieldMap, MappingDoc, Step, Suggestion, TargetColumn
from prospectra.ui.dnd.mime import ColumnPayload, column_mime
from prospectra.ui.mapping.mapper_panel import MapperPanel
from tests.test_ui_dnd import drop_on

SOURCE_COLUMNS = [("prod_nm", "VARCHAR"), ("colorway", "VARCHAR"), ("sku_raw", "VARCHAR")]


def pim_doc() -> MappingDoc:
    return MappingDoc(
        name="vendor_to_pim",
        target="pim_products",
        target_columns=[
            TargetColumn("styleCode", "VARCHAR", required=True),
            TargetColumn("styleDescription", "VARCHAR"),
        ],
    )


@pytest.fixture
def panel(qtbot):
    widget = MapperPanel(pim_doc(), SOURCE_COLUMNS)
    qtbot.addWidget(widget)
    return widget


def test_a_real_drop_maps_the_column(panel):
    """The plan's named assertion: the drop path driven through drop_on with a real payload."""
    payload = ColumnPayload("d1", "vendor", "/v.csv", ["prod_nm"], ["VARCHAR"])
    target_row = next(r for r in panel._rows if r.column.name == "styleDescription")

    drop_on(target_row, column_mime(payload))

    assert panel.doc().fields[0].sources == ["prod_nm"]
    assert panel.doc().fields[0].target == "styleDescription"


def test_the_drop_columns_seam_mirrors_the_drop(panel):
    panel.drop_columns("styleCode", ColumnPayload("d1", "v", "/v.csv", ["sku_raw"], ["VARCHAR"]))
    doc = panel.doc()
    assert doc.fields[0].target == "styleCode"
    assert doc.fields[0].sources == ["sku_raw"]


def test_an_unmapped_required_target_is_visibly_flagged(panel):
    assert "styleCode" in panel._banner.text()  # required, nothing mapped -> named in the banner
    panel.drop_columns("styleCode", ColumnPayload("d1", "v", "/v.csv", ["sku_raw"], ["VARCHAR"]))
    assert panel._banner.text().startswith("✓")


def test_an_upstream_rename_paints_the_row_red(qtbot):
    doc = pim_doc()
    doc.fields = [FieldMap(target="styleCode", sources=["sku_raw"])]
    panel = MapperPanel(doc, SOURCE_COLUMNS)
    qtbot.addWidget(panel)
    row = next(r for r in panel._rows if r.column.name == "styleCode")
    assert row._broken == []

    panel.set_available_columns([("prod_nm", "VARCHAR")])  # sku_raw renamed away upstream
    assert row._broken == ["sku_raw"]
    assert "no longer exist upstream" in panel._banner.text()


def test_suggestions_fill_only_empty_rows_and_only_when_accepted(panel):
    panel.drop_columns("styleCode", ColumnPayload("d1", "v", "/v.csv", ["sku_raw"], ["VARCHAR"]))
    panel.apply_suggestions(
        [
            Suggestion(source="prod_nm", target="styleDescription", confidence=0.8, reason="r"),
            Suggestion(source="colorway", target="styleCode", confidence=0.9, reason="r"),
        ]
    )
    by_target = {f.target: f for f in panel.doc().fields}
    assert by_target["styleDescription"].sources == ["prod_nm"]  # empty row: filled
    assert by_target["styleCode"].sources == ["sku_raw"]  # already mapped by hand: untouched


def test_transform_chips_write_steps_into_the_doc(panel):
    panel.drop_columns("styleCode", ColumnPayload("d1", "v", "/v.csv", ["sku_raw"], ["VARCHAR"]))
    row = next(r for r in panel._rows if r.column.name == "styleCode")
    row.field_map.steps.append(Step("upper", {}))
    row._add_chip(row.field_map.steps[0])
    doc = panel.doc()
    assert doc.fields[0].steps[0].key == "upper"


def test_the_note_survives_into_the_document(panel):
    panel.drop_columns("styleCode", ColumnPayload("d1", "v", "/v.csv", ["sku_raw"], ["VARCHAR"]))
    row = next(r for r in panel._rows if r.column.name == "styleCode")
    row._note.setText("vendor SKU leads with the style segment")
    assert panel.doc().fields[0].note == "vendor SKU leads with the style segment"


# -- the guided "Map to…" generator ------------------------------------------------------------


def test_flow_with_mapping_writes_a_runnable_flow(tmp_path):
    """The drop writes a FLOW (visible, editable, re-runnable) — never hidden magic."""
    source = tmp_path / "vendor.csv"
    source.write_text("sku_raw\nab12-NVY\n", encoding="utf-8")
    out = tmp_path / "mapped.csv"
    doc = MappingDoc(
        name="m",
        target_columns=[TargetColumn("styleCode")],
        fields=[
            FieldMap(
                target="styleCode",
                sources=["sku_raw"],
                steps=[Step("split_part", {"sep": "-", "index": 1}), Step("upper", {})],
            )
        ],
    )
    graph = flow_with_mapping(source, doc, out)
    assert len(graph.nodes) == 3  # Input → Map Fields → Output, on the canvas, not in the dark

    results = FlowRunner().run(graph)
    assert results[0].rows == 1
    assert out.read_text(encoding="utf-8").splitlines()[1] == "AB12"


def test_flow_with_mapping_refuses_a_broken_doc(tmp_path):
    doc = MappingDoc(
        name="m",
        target_columns=[TargetColumn("x", required=True)],
        fields=[],  # required target unmapped
    )
    with pytest.raises(ValueError, match="required"):
        flow_with_mapping(tmp_path / "s.csv", doc, tmp_path / "o.csv")


# -- the mapper inside a flow (the custom editor's services) -----------------------------------


def test_the_panel_previews_through_a_real_flow(qtbot, tmp_path):
    source = tmp_path / "vendor.csv"
    source.write_text("sku_raw\nab12-NVY\n", encoding="utf-8")
    graph = FlowGraph()
    input_id = graph.add_node("input_file", {"path": str(source)})
    mapper_id = graph.add_node("map_fields")
    graph.add_edge(input_id, mapper_id)
    runner = FlowRunner()

    doc = MappingDoc(
        name="m",
        target_columns=[TargetColumn("styleCode")],
        fields=[FieldMap(target="styleCode", sources=["sku_raw"], steps=[Step("upper", {})])],
    )
    panel = MapperPanel(
        doc,
        runner.columns(graph, input_id),
        preview_fn=lambda sql: runner.preview_select(graph, input_id, sql),
    )
    qtbot.addWidget(panel)
    panel.refresh_previews()
    row = next(r for r in panel._rows if r.column.name == "styleCode")
    # 2026-08-05: previews now run through the thread pool (they used to block the GUI thread,
    # re-preparing the upstream node once per mapped field), so the test waits for delivery.
    qtbot.waitUntil(lambda: "→" in row._preview.text(), timeout=5000)
    assert "ab12-NVY → AB12-NVY" in row._preview.text()
