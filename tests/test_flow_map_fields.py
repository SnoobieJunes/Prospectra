# 2026-07-31 (P7): The Map Fields node inside a real flow, plus the runner's P7 seams: the cheap
# `columns()` call (cached on the compiled SQL string, NOT node id — a node-id key goes stale on
# any upstream edit), `preview_select` (the mapper's live pane), and the shared-reference guard
# on the node's params dict.

from __future__ import annotations

import pytest

from prospectra.core.flow import NODE_TYPES, FlowGraph, FlowRunner, load_external_nodes
from prospectra.core.flow.node import Node
from prospectra.core.flow.nodes.map_fields import MapFieldsNode
from prospectra.core.mapping import FieldMap, MappingDoc, Step, TargetColumn


def vendor_csv(tmp_path):
    path = tmp_path / "vendor.csv"
    path.write_text(
        "prod_nm,colorway,sku_raw\nOxford Shirt,Navy,ab1234-NVY-M\nChore Coat,,cc9-OLV-L\n",
        encoding="utf-8",
    )
    return path


def pim_doc() -> dict:
    return MappingDoc(
        name="vendor_to_pim",
        target_columns=[
            TargetColumn("styleDescription", "VARCHAR", required=True),
            TargetColumn("styleCode", "VARCHAR", required=True),
        ],
        fields=[
            FieldMap(
                target="styleDescription",
                sources=["prod_nm", "colorway"],
                join_with=" - ",
                steps=[Step("truncate", {"length": 40})],
            ),
            FieldMap(
                target="styleCode",
                sources=["sku_raw"],
                steps=[Step("split_part", {"sep": "-", "index": 1}), Step("upper", {})],
            ),
        ],
    ).to_dict()


def mapped_graph(tmp_path, out_name="pim.csv"):
    graph = FlowGraph()
    source = graph.add_node("input_file", {"path": str(vendor_csv(tmp_path))})
    mapper = graph.add_node("map_fields", {"doc": pim_doc()})
    output = graph.add_node("output", {"path": str(tmp_path / out_name), "format": "csv"})
    graph.add_edge(source, mapper)
    graph.add_edge(mapper, output)
    return graph, mapper


def test_the_node_is_registered():
    assert NODE_TYPES["map_fields"] is MapFieldsNode


def test_two_instances_do_not_share_a_params_dict():
    """ParamField.default is a shared reference in Node.__init__ — a mutable default would make
    two mapping nodes on one canvas edit each other. Locked here."""
    first, second = MapFieldsNode(), MapFieldsNode()
    first.params["doc"]["name"] = "edited"
    assert second.params["doc"].get("name") != "edited"
    assert first.params["doc"] is not second.params["doc"]


def test_the_doc_rides_in_params_as_a_dict_not_a_string(tmp_path):
    graph, _mapper = mapped_graph(tmp_path)
    doc = graph.to_doc()
    node_doc = next(n for n in doc["nodes"] if n["type"] == "map_fields")
    assert isinstance(node_doc["params"]["doc"], dict)  # a string would double-encode
    rebuilt = FlowGraph.from_doc(doc)
    assert len(rebuilt.nodes) == 3


def test_the_flow_runs_end_to_end_and_maps_the_rows(tmp_path):
    graph, _mapper = mapped_graph(tmp_path)
    results = FlowRunner().run(graph)
    assert results[0].rows == 2
    lines = (tmp_path / "pim.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "styleDescription,styleCode"
    assert lines[1] == "Oxford Shirt - Navy,AB1234"
    assert lines[2] == "Chore Coat,CC9"  # concat_ws skipped the NULL colourway


def test_validation_speaks_before_anything_runs(tmp_path):
    node = MapFieldsNode({"doc": MappingDoc(name="empty").to_dict()})
    with pytest.raises(ValueError, match="at least one field"):
        node.validate()

    broken = pim_doc()
    broken["fields"] = broken["fields"][:1]  # styleCode required, now unmapped
    with pytest.raises(ValueError, match="styleCode"):
        MapFieldsNode({"doc": broken}).validate()


# -- file-backed crosswalks -------------------------------------------------------------------


def test_a_file_backed_crosswalk_is_materialized_and_used(tmp_path):
    xwalk = tmp_path / "colours.csv"
    xwalk.write_text("from,to\nNavy,NVY\nOlive,OLV\n", encoding="utf-8")
    doc = MappingDoc(
        name="colours",
        target_columns=[TargetColumn("colorCode")],
        fields=[
            FieldMap(
                target="colorCode",
                sources=["colorway"],
                steps=[Step("lookup", {"pairs": [], "file": str(xwalk)})],
            )
        ],
    )
    graph = FlowGraph()
    source = graph.add_node("input_file", {"path": str(vendor_csv(tmp_path))})
    mapper = graph.add_node("map_fields", {"doc": doc.to_dict()})
    graph.add_edge(source, mapper)

    preview = FlowRunner().preview(graph, mapper)
    values = [row[0] for row in preview.rows]
    assert values[0] == "NVY"  # translated through the file


def test_a_missing_crosswalk_file_is_an_error_not_an_empty_join(tmp_path):
    doc = MappingDoc(
        name="colours",
        target_columns=[TargetColumn("c")],
        fields=[
            FieldMap(
                target="c",
                sources=["colorway"],
                steps=[Step("lookup", {"pairs": [], "file": str(tmp_path / "gone.csv")})],
            )
        ],
    )
    graph = FlowGraph()
    source = graph.add_node("input_file", {"path": str(vendor_csv(tmp_path))})
    mapper = graph.add_node("map_fields", {"doc": doc.to_dict()})
    graph.add_edge(source, mapper)
    from prospectra.core.flow import FlowRunError

    with pytest.raises(FlowRunError, match="crosswalk file not found"):
        FlowRunner().preview(graph, mapper)


def test_duplicate_crosswalk_keys_are_confessed_not_crashed(tmp_path):
    xwalk = tmp_path / "dupes.csv"
    xwalk.write_text("from,to\nNavy,NVY\nNavy,NAV\n", encoding="utf-8")
    node = MapFieldsNode(
        {
            "doc": MappingDoc(
                name="m",
                target_columns=[TargetColumn("c")],
                fields=[
                    FieldMap(
                        target="c",
                        sources=["colorway"],
                        steps=[Step("lookup", {"pairs": [], "file": str(xwalk)})],
                    )
                ],
            ).to_dict()
        }
    )
    import duckdb

    con = duckdb.connect()
    try:
        node.prepare(con)
        assert any("duplicate key" in note for note in node.prepare_notes)
    finally:
        con.close()


# -- the runner's P7 seams --------------------------------------------------------------------


def test_columns_reports_the_mapped_schema_without_fetching_rows(tmp_path):
    graph, mapper = mapped_graph(tmp_path)
    runner = FlowRunner()
    names = [name for name, _dtype in runner.columns(graph, mapper)]
    assert names == ["styleDescription", "styleCode"]


def test_columns_cache_keys_on_the_sql_so_an_upstream_edit_invalidates(tmp_path):
    graph, mapper = mapped_graph(tmp_path)
    runner = FlowRunner()
    first = runner.columns(graph, mapper)
    assert len(runner._columns_cache) == 1

    # Same SQL -> served from the cache (poison it and observe the poisoned value come back).
    key = next(iter(runner._columns_cache))
    runner._columns_cache[key] = [("poisoned", "VARCHAR")]
    assert runner.columns(graph, mapper) == [("poisoned", "VARCHAR")]

    # An upstream edit changes the compiled SQL -> different key -> fresh answer, not the poison.
    doc = pim_doc()
    doc["fields"][1]["steps"][0]["args"]["index"] = 2
    graph.nodes[mapper].node.params["doc"] = doc
    fresh = runner.columns(graph, mapper)
    assert [n for n, _ in fresh] == [n for n, _ in first]
    assert fresh != [("poisoned", "VARCHAR")]


def test_preview_select_powers_the_before_after_pane(tmp_path):
    graph, mapper = mapped_graph(tmp_path)
    source = graph.inputs_of(mapper)[0]
    preview = FlowRunner().preview_select(
        graph,
        source,
        'SELECT "sku_raw" AS before, upper(split_part("sku_raw", \'-\', 1)) AS after FROM upstream',
        limit=5,
    )
    assert preview.columns == ["before", "after"]
    assert preview.rows[0] == ("ab1234-NVY-M", "AB1234")


def test_prepare_runs_each_ancestor_once_across_two_outputs(tmp_path):
    """run() visits every output; without the prepared-set guard a shared ancestor (imagine a
    live API fetch) would prepare once per output node."""
    calls: list[str] = []

    class CountingInput(Node):
        type_name = "counting_input_p7"
        display_name = "Counting input"
        category = "input"
        min_inputs = 0
        max_inputs = 0

        def prepare(self, con) -> None:
            calls.append("prepare")
            con.execute("CREATE OR REPLACE TABLE counted AS SELECT 1 AS n")

        def compile(self, inputs) -> str:
            return "SELECT * FROM counted"

    NODE_TYPES[CountingInput.type_name] = CountingInput
    try:
        graph = FlowGraph()
        source = graph.add_node("counting_input_p7")
        out_a = graph.add_node("output", {"path": str(tmp_path / "a.csv"), "format": "csv"})
        out_b = graph.add_node("output", {"path": str(tmp_path / "b.csv"), "format": "csv"})
        graph.add_edge(source, out_a)
        graph.add_edge(source, out_b)
        FlowRunner().run(graph)
        assert calls == ["prepare"]  # once, not once per output
    finally:
        NODE_TYPES.pop(CountingInput.type_name, None)


# -- the extension point that finally works ---------------------------------------------------


def test_load_external_nodes_actually_loads_a_plugin(monkeypatch):
    """`load_external_nodes()` had zero call sites before P7 — the documented extension point
    did not function. core.flow now calls it on import; this drives the loader directly."""

    class PluginNode(Node):
        type_name = "p7_plugin_node"
        display_name = "Plugin node"
        category = "transform"

        def compile(self, inputs) -> str:
            return f"SELECT * FROM {inputs[0]}"

    class FakeEntryPoint:
        name = "p7_plugin_node"

        @staticmethod
        def load():
            return PluginNode

    import prospectra.core.flow.node as node_module

    monkeypatch.setattr(
        node_module, "entry_points", lambda group: [FakeEntryPoint()] if group else []
    )
    try:
        load_external_nodes()
        assert NODE_TYPES["p7_plugin_node"] is PluginNode
    finally:
        NODE_TYPES.pop("p7_plugin_node", None)
