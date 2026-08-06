# 2026-08-05: Locks for the UI defects an adversarial review found. Each failed against P7 as
# first written. Two of them are the kind a data tool cannot afford: a credential following the
# user to a different host, and the screen disagreeing with the SQL that will actually run.

from __future__ import annotations

import pytest

from prospectra.core.flow import FlowGraph
from prospectra.core.http import Auth, HttpRequest
from prospectra.core.http.write import WriteSpec
from prospectra.core.mapping import MappingDoc, Step, TargetColumn
from prospectra.ui.api.playground import ApiPlaygroundTab
from prospectra.ui.flow.flow_tab import FlowTab
from prospectra.ui.flow.params_editor import ParamsEditor
from prospectra.ui.mapping.mapper_panel import MapperDialog, MapperPanel

# -- credentials -------------------------------------------------------------------------------


def test_a_typed_token_does_not_follow_you_to_another_host(qtbot):
    tab = ApiPlaygroundTab()
    qtbot.addWidget(tab)
    tab._editor.set_request(
        HttpRequest(url="https://alpha.example/v1", auth=Auth(kind="bearer", secret_ref="kc:a"))
    )
    tab._editor._token.setText("SECRET-FOR-ALPHA")

    tab.set_saved_requests(
        [
            (
                "id",
                "beta",
                HttpRequest(
                    url="https://beta.example/v1", auth=Auth(kind="bearer", secret_ref="kc:b")
                ),
            )
        ]
    )
    tab._load_saved(0)

    assert tab._editor.request().url == "https://beta.example/v1"
    assert tab._editor.token() == ""  # alpha's secret does not ride along


# -- the screen matches the SQL ----------------------------------------------------------------


def test_removing_a_repeated_transform_removes_the_one_that_was_clicked(qtbot):
    doc = MappingDoc(name="m", target_columns=[TargetColumn("out")])
    panel = MapperPanel(doc, [("a", "VARCHAR")])
    qtbot.addWidget(panel)
    row = panel._rows[0]
    row.add_sources(["a"])
    for key in ("trim", "upper", "trim"):
        row.field_map.steps.append(Step(key, {}))
        row._add_chip(row.field_map.steps[-1])

    row._remove_chip(row._chips[2])  # the LAST chip

    shown = [c.step.key for c in row._chips]
    compiled = [s.key for s in panel.doc().fields[0].steps]
    assert shown == compiled == ["trim", "upper"]


# -- a stale response cannot become a data source ----------------------------------------------


def test_editing_the_request_invalidates_the_previous_response(qtbot):
    tab = ApiPlaygroundTab()
    qtbot.addWidget(tab)
    tab._editor.set_request(HttpRequest(url="https://alpha.example/items"))
    tab._last_body = {"data": [{"a": 1}, {"a": 2}]}
    tab._last_body_url = "https://alpha.example/items"

    tab._editor._url.setText("https://beta.example/other")

    with pytest.raises(ValueError, match="send the request once first"):
        tab.mapping()


# -- the mapper dialog will not save something the runner would refuse -------------------------


def test_the_mapper_refuses_to_save_an_invalid_document(qtbot):
    doc = MappingDoc(name="m", target_columns=[TargetColumn("out")])
    dialog = MapperDialog(doc, [("a", "VARCHAR")])
    qtbot.addWidget(dialog)
    row = dialog.panel._rows[0]
    row.add_sources(["a"])
    row.field_map.constant = "both at once"  # validate() rejects sources + constant

    dialog._accept_if_valid()

    assert dialog.result() != int(MapperDialog.DialogCode.Accepted)
    assert "Cannot save yet" in dialog._problem.text()


# -- one run at a time -------------------------------------------------------------------------


def test_the_run_button_is_disabled_while_a_run_is_in_flight(qtbot, tmp_path):
    source = tmp_path / "rows.csv"
    source.write_text("a\n1\n", encoding="utf-8")
    tab = FlowTab()
    qtbot.addWidget(tab)
    src = tab._scene.add_node("input_file", tab._view.mapToScene(0, 0))
    tab.graph.nodes[src].node.params["path"] = str(source)
    sink = tab._scene.add_node("output", tab._view.mapToScene(200, 0))
    tab.graph.nodes[sink].node.params.update({"path": str(tmp_path / "out.csv"), "format": "csv"})
    tab._scene._connect(src, sink, 0)

    tab._run_flow()
    assert tab._run_button.isEnabled() is False  # a second click cannot start a second run
    qtbot.waitUntil(lambda: tab._run_button.isEnabled(), timeout=5000)


# -- the write editor can configure what it offers ---------------------------------------------


def test_selecting_header_auth_exposes_a_field_for_the_header_name(qtbot):
    graph = FlowGraph()
    node_id = graph.add_node("output_rest")
    editor = ParamsEditor()
    qtbot.addWidget(editor)
    editor.set_node(graph.nodes[node_id])

    from prospectra.ui.api.write_spec_editor import WriteSpecEditor

    spec_editor = editor.findChild(WriteSpecEditor)
    spec_editor._auth_kind.setCurrentText("header")
    spec_editor._auth_extra.setText("X-API-Key")
    spec_editor._url.setText("https://api.test/p/{sku}")
    spec_editor._key.setText("sku")

    spec = WriteSpec.from_dict(graph.nodes[node_id].node.params["spec"])
    assert spec.auth.header == "X-API-Key"
    spec.validate()  # no longer a dead end


def test_a_newer_write_spec_is_not_overwritten_with_defaults(qtbot):
    graph = FlowGraph()
    node_id = graph.add_node("output_rest")
    future = WriteSpec(url_template="https://api.test/x/{id}", key_column="id").to_dict()
    future["write_spec_schema"] = 99
    graph.nodes[node_id].node.params["spec"] = future

    editor = ParamsEditor()
    qtbot.addWidget(editor)
    editor.set_node(graph.nodes[node_id])
    from prospectra.ui.api.write_spec_editor import WriteSpecEditor

    spec_editor = editor.findChild(WriteSpecEditor)
    assert spec_editor._readable is False
    assert not hasattr(spec_editor, "_url")  # no form is rendered, so nothing can overwrite it
    spec_editor._write_back()  # even if something calls it, the document is left alone

    assert graph.nodes[node_id].node.params["spec"]["write_spec_schema"] == 99
    assert graph.nodes[node_id].node.params["spec"]["url_template"] == "https://api.test/x/{id}"


# -- hostile column names cannot spoof the mapper ----------------------------------------------


def test_a_hostile_column_name_is_escaped_in_the_field_row(qtbot):
    from prospectra.ui.mapping.field_row import FieldRow

    row = FieldRow(TargetColumn("<b>totally</b> safe", "VARCHAR"))
    qtbot.addWidget(row)
    label = row.findChildren(type(row._sources))[0]
    assert "&lt;b&gt;" in label.text()


# -- the runner's schema cache does not outlive the graph --------------------------------------


def test_editing_the_graph_clears_the_schema_cache(qtbot, tmp_path):
    source = tmp_path / "rows.csv"
    source.write_text("a\n1\n", encoding="utf-8")
    tab = FlowTab()
    qtbot.addWidget(tab)
    src = tab._scene.add_node("input_file", tab._view.mapToScene(0, 0))
    tab.graph.nodes[src].node.params["path"] = str(source)
    assert tab._runner.columns(tab.graph, src) == [("a", "BIGINT")]
    assert tab._runner._columns_cache

    source.write_text("a,b\n1,2\n", encoding="utf-8")
    tab._graph_changed()
    assert tab._runner._columns_cache == {}
    assert [n for n, _ in tab._runner.columns(tab.graph, src)] == ["a", "b"]
