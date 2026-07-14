# 2026-07-13 (P2): Flow engine coverage — graph invariants (cycles, port capacity, readiness),
# every built-in node's compiled SQL against real DuckDB data, doc round-trip, and the
# sampleflow.png-shaped pipeline (multi-input → clean → union → join → aggregate → pivot → output)
# that is the phase's acceptance criterion.

import pytest

from prospectra.core.flow import FlowGraph, FlowGraphError, FlowRunError, FlowRunner
from prospectra.core.flow.compiler import compile_sql


@pytest.fixture()
def runner():
    return FlowRunner()


@pytest.fixture()
def orders_csv(tmp_path):
    path = tmp_path / "orders.csv"
    path.write_text(
        "region,rep,sales\nWest,ann,100\nWest,bob,50\nEast,ann,20\nEast,,7\n", encoding="utf-8"
    )
    return path


def _single_input(path):
    graph = FlowGraph()
    src = graph.add_node("input_file", {"path": str(path)})
    return graph, src


# -- graph invariants ---------------------------------------------------------------------


def test_cycle_is_rejected(orders_csv):
    # Union has unlimited inputs, so the capacity check cannot mask the cycle check here.
    graph, src = _single_input(orders_csv)
    other = graph.add_node("input_file", {"path": str(orders_csv)})
    union = graph.add_node("union")
    flt = graph.add_node("filter", {"expression": "sales > 1"})
    graph.add_edge(src, union)
    graph.add_edge(other, union)
    graph.add_edge(union, flt)
    with pytest.raises(FlowGraphError, match="cycle"):
        graph.add_edge(flt, union)  # would feed the union from its own descendant


def test_single_input_port_capacity(orders_csv):
    graph, src = _single_input(orders_csv)
    other = graph.add_node("input_file", {"path": str(orders_csv)})
    flt = graph.add_node("filter", {"expression": "sales > 0"})
    graph.add_edge(src, flt)
    with pytest.raises(FlowGraphError, match="already connected"):
        graph.add_edge(other, flt)


def test_union_accepts_many_inputs(orders_csv, runner):
    graph = FlowGraph()
    a = graph.add_node("input_file", {"path": str(orders_csv)})
    b = graph.add_node("input_file", {"path": str(orders_csv)})
    c = graph.add_node("input_file", {"path": str(orders_csv)})
    u = graph.add_node("union")
    for src in (a, b, c):
        graph.add_edge(src, u)
    assert runner.preview(graph, u).total_rows == 12


def test_missing_input_is_reported(orders_csv):
    graph = FlowGraph()
    flt = graph.add_node("filter", {"expression": "sales > 0"})
    with pytest.raises(FlowGraphError, match="needs 1 input"):
        graph.validate_ready(flt)


def test_bad_params_are_reported(orders_csv):
    graph, src = _single_input(orders_csv)
    calc = graph.add_node("calculated", {"name": "", "expression": "1"})
    graph.add_edge(src, calc)
    with pytest.raises(FlowGraphError, match="name the new column"):
        graph.validate_ready(calc)


def test_bad_sql_is_attributed_to_its_node(orders_csv, runner):
    graph, src = _single_input(orders_csv)
    flt = graph.add_node("filter", {"expression": "no_such_column > 1"})
    graph.add_edge(src, flt)
    with pytest.raises(FlowRunError) as excinfo:
        runner.preview(graph, flt)
    assert excinfo.value.node_id == flt  # canvas can point at the offending node


# -- nodes -------------------------------------------------------------------------------


def test_filter_and_calculated(orders_csv, runner):
    graph, src = _single_input(orders_csv)
    flt = graph.add_node("filter", {"expression": "region = 'West'"})
    calc = graph.add_node("calculated", {"name": "log_sales", "expression": "ln(sales)"})
    graph.add_edge(src, flt)
    graph.add_edge(flt, calc)
    preview = runner.preview(graph, calc)
    assert preview.total_rows == 2
    assert "log_sales" in [c[0] for c in preview.columns]


def test_select_rename_cast_and_drop(orders_csv, runner):
    graph, src = _single_input(orders_csv)
    sel = graph.add_node(
        "select", {"drop": "rep", "rename": "sales:amount", "cast": "sales:DOUBLE"}
    )
    graph.add_edge(src, sel)
    preview = runner.preview(graph, sel)
    names = [c[0] for c in preview.columns]
    assert names == ["region", "amount"]
    assert dict(preview.columns)["amount"] == "DOUBLE"


def test_select_keep_only(orders_csv, runner):
    graph, src = _single_input(orders_csv)
    sel = graph.add_node("select", {"keep": "region,sales"})
    graph.add_edge(src, sel)
    assert [c[0] for c in runner.preview(graph, sel).columns] == ["region", "sales"]


def test_clean_nulls_drop_and_fill(orders_csv, runner):
    graph, src = _single_input(orders_csv)
    drop = graph.add_node("clean_nulls", {"mode": "drop", "columns": "rep"})
    graph.add_edge(src, drop)
    assert runner.preview(graph, drop).total_rows == 3  # the empty rep row is gone

    graph2, src2 = _single_input(orders_csv)
    fill = graph2.add_node(
        "clean_nulls", {"mode": "fill", "columns": "rep", "fill_value": "unknown"}
    )
    graph2.add_edge(src2, fill)
    result = runner.preview(graph2, fill)
    assert result.total_rows == 4
    assert "unknown" in [row[1] for row in result.rows]


def test_aggregate(orders_csv, runner):
    graph, src = _single_input(orders_csv)
    agg = graph.add_node("aggregate", {"group_by": "region", "aggregations": "sum(sales) AS total"})
    graph.add_edge(src, agg)
    preview = runner.preview(graph, agg)
    assert dict(preview.rows) == {"West": 150, "East": 27}


def test_join_matching_keys(orders_csv, tmp_path, runner):
    quota = tmp_path / "quota.csv"
    quota.write_text("region,quota\nWest,120\nEast,30\n", encoding="utf-8")
    graph, orders = _single_input(orders_csv)
    quotas = graph.add_node("input_file", {"path": str(quota)})
    agg = graph.add_node("aggregate", {"group_by": "region", "aggregations": "sum(sales) AS total"})
    join = graph.add_node("join", {"how": "inner", "left_on": "region"})
    graph.add_edge(orders, agg)
    graph.add_edge(agg, join, port=0)
    graph.add_edge(quotas, join, port=1)
    preview = runner.preview(graph, join)
    assert [c[0] for c in preview.columns] == ["region", "total", "quota"]  # key deduped
    assert preview.total_rows == 2


def test_pivot_and_unpivot_roundtrip(orders_csv, runner):
    graph, src = _single_input(orders_csv)
    pivot = graph.add_node("pivot", {"on": "region", "using": "sum(sales)", "group_by": "rep"})
    graph.add_edge(src, pivot)
    wide = runner.preview(graph, pivot)
    assert {"West", "East"} <= set(c[0] for c in wide.columns)

    unpivot = graph.add_node(
        "unpivot", {"columns": "West,East", "name_to": "region", "value_to": "sales"}
    )
    graph.add_edge(pivot, unpivot)
    long = runner.preview(graph, unpivot)
    assert [c[0] for c in long.columns] == ["rep", "region", "sales"]


def test_outliers_flag_and_remove(tmp_path, runner):
    path = tmp_path / "spikes.csv"
    rows = "\n".join(str(v) for v in [10, 11, 9, 10, 12, 900])
    path.write_text(f"v\n{rows}\n", encoding="utf-8")
    graph, src = _single_input(path)
    flag = graph.add_node("outliers", {"column": "v", "method": "iqr", "action": "flag"})
    graph.add_edge(src, flag)
    flagged = runner.preview(graph, flag)
    assert [c[0] for c in flagged.columns] == ["v", "is_outlier"]
    assert sum(1 for row in flagged.rows if row[1]) == 1  # only the 900

    graph2, src2 = _single_input(path)
    remove = graph2.add_node(
        "outliers", {"column": "v", "method": "zscore", "factor": 1.5, "action": "remove"}
    )
    graph2.add_edge(src2, remove)
    assert runner.preview(graph2, remove).total_rows == 5


def test_sample_is_seeded(runner, tmp_path):
    path = tmp_path / "many.csv"
    path.write_text("n\n" + "\n".join(str(i) for i in range(1000)) + "\n", encoding="utf-8")
    graph, src = _single_input(path)
    node = graph.add_node("sample", {"rows": 25, "seed": 7})
    graph.add_edge(src, node)
    first = runner.preview(graph, node).rows
    second = runner.preview(graph, node).rows
    assert len(first) == 25
    assert first == second  # same seed -> identical sample (findings stay reproducible)


# -- persistence & the acceptance pipeline --------------------------------------------------


def test_doc_roundtrip(orders_csv, runner):
    graph, src = _single_input(orders_csv)
    flt = graph.add_node("filter", {"expression": "sales > 10"}, pos=(120.0, 40.0))
    graph.add_edge(src, flt)
    restored = FlowGraph.from_doc(graph.to_doc())
    assert restored.nodes[flt].x == 120.0
    assert runner.preview(restored, flt).total_rows == runner.preview(graph, flt).total_rows


def test_future_flow_schema_refused():
    with pytest.raises(FlowGraphError, match="newer"):
        FlowGraph.from_doc({"flow_schema": 999, "nodes": [], "edges": []})


def test_sampleflow_shaped_pipeline(tmp_path, runner):
    """The sampleflow.png shape: two regional inputs → clean → union → join quotas →
    aggregate → pivot → CSV output. This is the P2 acceptance criterion."""
    west = tmp_path / "orders_west.csv"
    west.write_text("region,rep,sales\nWest,ann,100\nWest,bob,50\nWest,,5\n", encoding="utf-8")
    east = tmp_path / "orders_east.csv"
    east.write_text("region,rep,sales\nEast,ann,20\nEast,cat,7\n", encoding="utf-8")
    quotas = tmp_path / "quotas.csv"
    quotas.write_text("region,quota\nWest,120\nEast,30\n", encoding="utf-8")
    out = tmp_path / "out" / "prepped.csv"

    graph = FlowGraph()
    in_west = graph.add_node("input_file", {"path": str(west)})
    in_east = graph.add_node("input_file", {"path": str(east)})
    in_quota = graph.add_node("input_file", {"path": str(quotas)})
    clean = graph.add_node("clean_nulls", {"mode": "drop", "columns": "rep"})
    union = graph.add_node("union")
    agg = graph.add_node(
        "aggregate", {"group_by": "region,rep", "aggregations": "sum(sales) AS total_sales"}
    )
    join = graph.add_node("join", {"how": "left", "left_on": "region"})
    calc = graph.add_node(
        "calculated", {"name": "pct_of_quota", "expression": "total_sales / quota"}
    )
    pivot = graph.add_node(
        "pivot", {"on": "region", "using": "sum(total_sales)", "group_by": "rep"}
    )
    output = graph.add_node("output", {"path": str(out), "format": "csv"})

    graph.add_edge(in_west, clean)
    graph.add_edge(clean, union)
    graph.add_edge(in_east, union)
    graph.add_edge(union, agg)
    graph.add_edge(agg, join, port=0)
    graph.add_edge(in_quota, join, port=1)
    graph.add_edge(join, calc)
    graph.add_edge(calc, pivot)
    graph.add_edge(pivot, output)

    # the whole prep pipeline compiles to ONE DuckDB statement
    assert compile_sql(graph, output).count("WITH") == 1

    joined = runner.preview(graph, calc)
    assert {"region", "rep", "total_sales", "quota", "pct_of_quota"} == {
        c[0] for c in joined.columns
    }
    assert joined.total_rows == 4  # the null-rep West row was cleaned out

    (result,) = runner.run(graph)
    assert result.rows == 3  # ann, bob, cat
    written = out.read_text(encoding="utf-8").splitlines()
    assert written[0].split(",")[0] == "rep"
    assert {"West", "East"} <= set(written[0].split(","))

    profile = runner.profile(graph, calc)
    assert profile.row_count == 4
    assert {c.name for c in profile.columns} == {c[0] for c in joined.columns}
