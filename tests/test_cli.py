# 2026-07-13 (P2): run-flow is implemented — it now runs a saved flow headless (the CI path that
# exercises the whole engine without a display). Its stub test became a real end-to-end test.
# 2026-07-13 (P0): CLI contract — stubs must exit 2 with an honest "not implemented" message
# (never pretend to work), and generate-example must produce the seeded dataset.

import pytest

from prospectra import __version__
from prospectra.cli import main
from prospectra.core.flow import FlowGraph
from prospectra.core.project import ProjectStore


def test_scan_end_to_end(tmp_path, capsys):
    """The P3 acceptance path: point the CLI at the tutorial dataset and require the ranked table
    to lead with the planted driver while the decoys stay out of the findings."""
    from prospectra.example_data import write_csv

    path = write_csv(tmp_path / "ice.csv", days=500)
    assert main(["scan", str(path), "--target", "ice_cream_sales", "--pca"]) == 0

    out = capsys.readouterr().out
    assert "WHAT EXPLAINS ice_cream_sales" in out
    # the ranked table leads with the strongest planted driver
    ranked = out.split("WHAT EXPLAINS")[1].splitlines()
    first_row = next(line for line in ranked[2:] if line.strip())
    assert first_row.split()[0] == "temperature_c"
    # the combined model recovers the planted equation, and PCA teaches what it is
    assert "BEST COMBINED MODEL" in out
    assert "TRUST:" in out
    assert "never looked at your target" in out
    # decoys are reported as rejected, not as findings
    rejected = out.split("rejected by FDR")[1]
    assert "lottery_numbers" in rejected


def test_scan_rejects_a_bad_target(tmp_path, capsys):
    from prospectra.example_data import write_csv

    path = write_csv(tmp_path / "ice.csv", days=60)
    assert main(["scan", str(path), "--target", "not_a_column"]) == 1
    assert "Cannot use" in capsys.readouterr().err


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


# 2026-07-14 (P5): `scrape` — the whole scrape path (fetch → parse → emit) driven headless, with no
# network: the CLI accepts a local .html file, which is exactly how CI exercises it on all 3 OSes.
def test_scrape_writes_csvs_a_scan_can_read(tmp_path, capsys):
    page = tmp_path / "countries.html"
    page.write_text(
        "<html><body><h2>GDP</h2><table><caption>GDP by country</caption>"
        "<tr><th>Country</th><th>GDP</th></tr>"
        "<tr><td>United States</td><td>27720700</td></tr>"
        "<tr><td>China</td><td>17794782</td></tr></table></body></html>",
        encoding="utf-8",
    )
    out_dir = tmp_path / "scraped"
    assert main(["scrape", str(page), "--out", str(out_dir), "--tables-only"]) == 0

    out = capsys.readouterr().out
    assert "1 table(s)" in out
    written = list(out_dir.glob("*.csv"))
    assert len(written) == 1
    assert written[0].read_text(encoding="utf-8").splitlines()[0] == "Country,GDP"


def test_scrape_reports_a_page_with_no_tables_instead_of_writing_junk(tmp_path, capsys):
    page = tmp_path / "empty.html"
    page.write_text("<html><body><p>Nothing tabular here.</p></body></html>", encoding="utf-8")
    assert main(["scrape", str(page), "--out", str(tmp_path / "out"), "--tables-only"]) == 1
    assert "No data tables found" in capsys.readouterr().err
