# 2026-07-13 (P2): Flow canvas UI coverage — the scene mirrors the graph model, rejects illegal
# connections instead of corrupting it, the params editor writes back through the schema, and the
# tab previews/profiles a real pipeline end to end (offscreen).

import pytest

from prospectra.core.flow import FlowGraph
from prospectra.ui.flow.canvas import FlowScene
from prospectra.ui.flow.flow_tab import FlowTab
from prospectra.ui.flow.params_editor import ParamsEditor
from prospectra.ui.main_window import MainWindow


@pytest.fixture()
def orders_csv(tmp_path):
    path = tmp_path / "orders.csv"
    path.write_text("region,sales\nWest,100\nWest,50\nEast,20\n", encoding="utf-8")
    return path


def test_scene_mirrors_graph(qtbot, orders_csv):
    graph = FlowGraph()
    scene = FlowScene(graph)
    src = scene.add_node("input_file", _pt(0, 0))
    dst = scene.add_node("filter", _pt(200, 0))
    scene._connect(src, dst, 0)
    assert len(graph.edges) == 1
    assert len(scene._edges) == 1
    # deleting the node prunes its edges from both model and scene
    graph.remove_node(dst)
    scene.rebuild()
    assert graph.edges == []
    assert scene._edges == []


def test_scene_rejects_illegal_edge_without_corrupting_graph(qtbot, orders_csv):
    graph = FlowGraph()
    scene = FlowScene(graph)
    rejected: list[str] = []
    scene.edge_rejected.connect(rejected.append)

    a = scene.add_node("input_file", _pt(0, 0))
    b = scene.add_node("input_file", _pt(0, 100))
    flt = scene.add_node("filter", _pt(200, 0))
    scene._connect(a, flt, 0)
    scene._connect(b, flt, 0)  # filter's only input port is taken

    assert len(graph.edges) == 1
    assert rejected and "already connected" in rejected[0]


def test_params_editor_writes_back(qtbot):
    graph = FlowGraph()
    node_id = graph.add_node("filter")
    editor = ParamsEditor()
    qtbot.addWidget(editor)
    editor.set_node(graph.nodes[node_id])

    from PySide6.QtWidgets import QLineEdit

    line = editor.findChildren(QLineEdit)[0]
    line.setText("sales > 10")
    assert graph.nodes[node_id].node.params["expression"] == "sales > 10"


# 2026-07-31 (P7): the corruption lock. The old editor fell through to QLineEdit for any kind it
# did not know — which str(dict)'d a structured param into a text box and wrote the Python repr
# back on the next keystroke. An unknown kind must now render NO QLineEdit at all.
def test_an_unknown_param_kind_renders_no_line_edit(qtbot):
    from typing import ClassVar

    from PySide6.QtWidgets import QLineEdit

    from prospectra.core.flow.node import NODE_TYPES, Node, ParamField

    class WeirdNode(Node):
        type_name = "weird_kind_node_p7"
        display_name = "Weird"
        category = "transform"
        params_schema: ClassVar = (ParamField("blob", "Blob", "some_future_kind", None),)

        def compile(self, inputs):
            return f"SELECT * FROM {inputs[0]}"

    NODE_TYPES[WeirdNode.type_name] = WeirdNode
    try:
        graph = FlowGraph()
        node_id = graph.add_node("weird_kind_node_p7", {"blob": {"structured": True}})
        editor = ParamsEditor()
        qtbot.addWidget(editor)
        editor.set_node(graph.nodes[node_id])

        assert editor.findChildren(QLineEdit) == []  # nothing that could write a repr back
        assert graph.nodes[node_id].node.params["blob"] == {"structured": True}
    finally:
        NODE_TYPES.pop(WeirdNode.type_name, None)


def test_a_custom_editor_is_consulted_before_the_builtin_kinds(qtbot):
    from typing import ClassVar

    from PySide6.QtWidgets import QLabel

    from prospectra.core.flow.node import NODE_TYPES, Node, ParamField
    from prospectra.ui.flow.params_editor import CUSTOM_EDITORS

    class CustomNode(Node):
        type_name = "custom_kind_node_p7"
        display_name = "Custom"
        category = "transform"
        params_schema: ClassVar = (ParamField("doc", "Doc", "test_custom_kind", None),)

        def compile(self, inputs):
            return f"SELECT * FROM {inputs[0]}"

    NODE_TYPES[CustomNode.type_name] = CustomNode
    CUSTOM_EDITORS["test_custom_kind"] = lambda editor, inst, field: QLabel("custom editor here")
    try:
        graph = FlowGraph()
        node_id = graph.add_node("custom_kind_node_p7")
        editor = ParamsEditor()
        qtbot.addWidget(editor)
        editor.set_node(graph.nodes[node_id])
        labels = [w.text() for w in editor.findChildren(QLabel)]
        assert "custom editor here" in labels
    finally:
        NODE_TYPES.pop(CustomNode.type_name, None)
        CUSTOM_EDITORS.pop("test_custom_kind", None)


def test_the_p7_param_kinds_have_registered_editors(qtbot):
    """mapping_doc and write_spec render real editors — not the read-only fallback label."""
    import prospectra.ui.mapping  # noqa: F401  (registration import)
    from prospectra.ui.flow.params_editor import CUSTOM_EDITORS

    assert "mapping_doc" in CUSTOM_EDITORS
    assert "write_spec" in CUSTOM_EDITORS

    graph = FlowGraph()
    node_id = graph.add_node("output_rest")
    editor = ParamsEditor()
    qtbot.addWidget(editor)
    editor.set_node(graph.nodes[node_id])

    from PySide6.QtWidgets import QLineEdit

    url_edits = editor.findChildren(QLineEdit)
    assert url_edits  # the write-spec form rendered
    url_edits[0].setText("https://api.test/things/{sku}")
    assert (
        graph.nodes[node_id].node.params["spec"]["url_template"] == "https://api.test/things/{sku}"
    )


def test_flow_tab_previews_and_profiles(qtbot, orders_csv):
    tab = FlowTab()
    qtbot.addWidget(tab)
    src = tab._scene.add_node("input_file", _pt(0, 0))
    tab.graph.nodes[src].node.params["path"] = str(orders_csv)
    agg = tab._scene.add_node("aggregate", _pt(220, 0))
    tab.graph.nodes[agg].node.params.update(
        {"group_by": "region", "aggregations": "sum(sales) AS total"}
    )
    tab._scene._connect(src, agg, 0)

    tab._preview_node(agg)
    qtbot.waitUntil(lambda: "2 rows" in tab._status.text(), timeout=5000)
    assert tab._preview_table.columnCount() == 2
    qtbot.waitUntil(lambda: tab._cards._layout.count() > 1, timeout=5000)  # profile cards arrived

    tab._refresh_changes()
    assert tab._changes.count() == 2  # both steps listed in run order


def test_flow_tab_reports_bad_node(qtbot, orders_csv):
    tab = FlowTab()
    qtbot.addWidget(tab)
    src = tab._scene.add_node("input_file", _pt(0, 0))
    tab.graph.nodes[src].node.params["path"] = str(orders_csv)
    flt = tab._scene.add_node("filter", _pt(220, 0))
    tab.graph.nodes[flt].node.params["expression"] = "no_such_column > 1"
    tab._scene._connect(src, flt, 0)

    tab._preview_node(flt)
    qtbot.waitUntil(lambda: tab._status.text().startswith("Error:"), timeout=5000)
    assert tab._scene._nodes[flt].error is not None  # node is flagged on the canvas


def test_flow_saves_and_reopens_through_project(qtbot, tmp_path, orders_csv):
    from prospectra.core.project import ProjectStore

    window = MainWindow()
    qtbot.addWidget(window)
    tab = window._flow_tab
    src = tab._scene.add_node("input_file", _pt(10, 20))
    tab.graph.nodes[src].node.params["path"] = str(orders_csv)
    out = tab._scene.add_node("output", _pt(240, 20))
    tab.graph.nodes[out].node.params.update({"path": str(tmp_path / "o.csv"), "format": "csv"})
    tab._scene._connect(src, out, 0)

    store = ProjectStore.create(tmp_path / "p.prospectra")
    window._attach(store)
    record = store.save_flow("nightly", tab.graph.to_doc())

    fresh = FlowGraph.from_doc(store.get_flow(record.id).doc)
    tab.load_graph(fresh)
    assert len(tab.graph.nodes) == 2
    assert len(tab.graph.edges) == 1
    assert tab.graph.nodes[src].x == 10.0  # canvas positions survive the round trip
    assert len(tab._scene._nodes) == 2
    window.close()


def _pt(x, y):
    from PySide6.QtCore import QPointF

    return QPointF(x, y)
