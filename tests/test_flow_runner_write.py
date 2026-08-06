# 2026-07-31 (P7): The generalized write path and its guards. The two load-bearing behaviours:
#   * a `destructive` node makes run() (and the CLI) REFUSE up front — before ANY output runs —
#     unless writes were explicitly allowed. "Run flow" firing live PUTs by accident is the
#     single most dangerous failure this app could have;
#   * a node that cannot write RAISES from the base class — a silent no-op would report success
#     having done nothing.

from __future__ import annotations

from typing import ClassVar

import duckdb
import pytest

from prospectra.core.flow import (
    NODE_TYPES,
    FlowGraph,
    FlowRunError,
    FlowRunner,
    Node,
    WriteReport,
)


class FakeRestWrite(Node):
    """Stands in for slice 7's RestWriteNode: an output that would touch a live system."""

    type_name = "fake_rest_write_p7"
    display_name = "Fake REST write"
    category = "output"
    destructive: ClassVar[bool] = True
    sent: ClassVar[list[str]] = []

    def compile(self, inputs):
        return f"SELECT * FROM {inputs[0]}"

    def write(self, con, sql, *, dry_run=True):
        if dry_run:
            return WriteReport(attempted=1, skipped=1, dry_run=True, notes=["dry run"])
        type(self).sent.append(sql)
        return WriteReport(attempted=1, written=1)


@pytest.fixture(autouse=True)
def _register_fake():
    NODE_TYPES[FakeRestWrite.type_name] = FakeRestWrite
    FakeRestWrite.sent = []
    yield
    NODE_TYPES.pop(FakeRestWrite.type_name, None)


def graph_with_write(tmp_path):
    source = tmp_path / "rows.csv"
    source.write_text("sku\nA-1\n", encoding="utf-8")
    graph = FlowGraph()
    src = graph.add_node("input_file", {"path": str(source)})
    sink = graph.add_node("fake_rest_write_p7")
    graph.add_edge(src, sink)
    return graph, sink


def test_a_destructive_node_refuses_without_allow_writes(tmp_path):
    graph, _sink = graph_with_write(tmp_path)
    with pytest.raises(FlowRunError, match="live writes"):
        FlowRunner().run(graph)
    assert FakeRestWrite.sent == []  # NOTHING went out


def test_the_refusal_happens_before_any_other_output_runs(tmp_path):
    """All-or-nothing pre-flight: the safe file output must NOT run and then have the flow die
    on the write — the user would get half a run and a mess to reason about."""
    graph, _sink = graph_with_write(tmp_path)
    out = tmp_path / "safe.csv"
    src = next(iter(graph.nodes))  # the input node (only non-output at this point)
    safe = graph.add_node("output", {"path": str(out), "format": "csv"})
    graph.add_edge(src, safe)

    with pytest.raises(FlowRunError):
        FlowRunner().run(graph)
    assert not out.exists()  # the safe output did not run either — refusal is up-front


def test_allow_writes_lets_the_write_happen(tmp_path):
    graph, _sink = graph_with_write(tmp_path)
    results = FlowRunner().run(graph, allow_writes=True)
    assert results[0].written == 1
    assert FakeRestWrite.sent != []


def test_dry_run_rehearses_without_sending(tmp_path):
    graph, _sink = graph_with_write(tmp_path)
    results = FlowRunner().run(graph, dry_run=True)
    assert results[0].dry_run is True
    assert FakeRestWrite.sent == []


def test_only_runs_the_named_output(tmp_path):
    graph, sink = graph_with_write(tmp_path)
    out = tmp_path / "safe.csv"
    src = graph.inputs_of(sink)[0]
    safe = graph.add_node("output", {"path": str(out), "format": "csv"})
    graph.add_edge(src, safe)

    results = FlowRunner().run(graph, only=[safe])
    assert len(results) == 1 and results[0].path == str(out)
    assert FakeRestWrite.sent == []  # the write node was not in the subset


def test_a_node_that_cannot_write_raises_instead_of_pretending():
    node = NODE_TYPES["select"]()
    with pytest.raises(NotImplementedError, match="select cannot write"):
        node.write(duckdb.connect(), "SELECT 1")


def test_file_output_dry_run_counts_but_writes_nothing(tmp_path):
    source = tmp_path / "rows.csv"
    source.write_text("a\n1\n2\n", encoding="utf-8")
    out = tmp_path / "out.csv"
    graph = FlowGraph()
    src = graph.add_node("input_file", {"path": str(source)})
    sink = graph.add_node("output", {"path": str(out), "format": "csv"})
    graph.add_edge(src, sink)

    results = FlowRunner().run(graph, dry_run=True)
    assert results[0].attempted == 2
    assert not out.exists()
    assert any("dry run" in note for note in results[0].notes)


# -- the local-dataset destination -------------------------------------------------------------


def test_output_dataset_lands_a_durable_duckdb_table(tmp_path):
    source = tmp_path / "rows.csv"
    source.write_text("sku,qty\nA-1,3\nB-2,5\n", encoding="utf-8")
    database = tmp_path / "local.duckdb"
    graph = FlowGraph()
    src = graph.add_node("input_file", {"path": str(source)})
    sink = graph.add_node("output_dataset", {"database": str(database), "table": "mapped_rows"})
    graph.add_edge(src, sink)

    results = FlowRunner().run(graph)
    assert results[0].written == 2
    assert database.exists()

    con = duckdb.connect(str(database))  # durable: a NEW connection sees the table
    try:
        assert con.execute("SELECT count(*) FROM mapped_rows").fetchone()[0] == 2
    finally:
        con.close()

    # CREATE OR REPLACE: re-running refreshes rather than duplicating
    results = FlowRunner().run(graph)
    assert results[0].written == 2


def test_output_dataset_validates_its_table_name(tmp_path):
    graph = FlowGraph()
    graph.add_node("output_dataset", {"database": str(tmp_path / "x.duckdb"), "table": "1; DROP"})
    node = next(iter(graph.nodes.values())).node
    with pytest.raises(ValueError, match="table name"):
        node.validate()
