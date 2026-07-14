# 2026-07-13 (P2): run-flow is implemented — it now runs a saved flow headless (the CI path that
# exercises the whole engine without a display). Its stub test became a real end-to-end test.
# 2026-07-13 (P0): CLI contract — stubs must exit 2 with an honest "not implemented" message
# (never pretend to work), and generate-example must produce the seeded dataset.

import pytest

from prospectra import __version__
from prospectra.cli import main
from prospectra.core.flow import FlowGraph
from prospectra.core.project import ProjectStore


def test_scan_is_an_honest_stub(capsys):
    assert main(["scan", "data.csv", "--target", "sales"]) == 2
    assert "P3" in capsys.readouterr().err


def test_run_flow_end_to_end(tmp_path, capsys):
    source = tmp_path / "orders.csv"
    source.write_text("region,sales\nWest,100\nWest,50\nEast,20\n", encoding="utf-8")
    out = tmp_path / "out" / "totals.csv"

    graph = FlowGraph()
    src = graph.add_node("input_file", {"path": str(source)})
    agg = graph.add_node("aggregate", {"group_by": "region", "aggregations": "sum(sales) AS total"})
    sink = graph.add_node("output", {"path": str(out), "format": "csv"})
    graph.add_edge(src, agg)
    graph.add_edge(agg, sink)

    project = tmp_path / "p.prospectra"
    with ProjectStore.create(project) as store:
        store.save_flow("totals", graph.to_doc())

    assert main(["run-flow", str(project), "totals"]) == 0
    assert "2 rows" in capsys.readouterr().out
    written = out.read_text(encoding="utf-8").splitlines()
    assert written[0] == "region,total"
    assert sorted(written[1:]) == ["East,20", "West,150"]


def test_run_flow_missing_flow_is_reported(tmp_path, capsys):
    project = tmp_path / "p.prospectra"
    ProjectStore.create(project).close()
    assert main(["run-flow", str(project), "ghost"]) == 1
    assert "no flow" in capsys.readouterr().err


def test_generate_example(tmp_path, capsys):
    out = tmp_path / "ice.csv"
    assert main(["generate-example", str(out), "--days", "10"]) == 0
    assert out.exists()
    assert str(out) in capsys.readouterr().out


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out
