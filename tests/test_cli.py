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


# 2026-07-31 (P7): the write-back hazard, at the CLI. A flow containing a live REST write must
# exit 2 AND name the node without --allow-writes — silently skipping it would leave the user
# believing the flow ran.
def _write_flow_project(tmp_path):
    from prospectra.core.http.write import WriteSpec

    source = tmp_path / "rows.csv"
    source.write_text("sku\nA-1\n", encoding="utf-8")
    graph = FlowGraph()
    src = graph.add_node("input_file", {"path": str(source)})
    sink = graph.add_node(
        "output_rest",
        {
            "spec": WriteSpec(
                url_template="https://api.test/products/{sku}", method="PUT", key_column="sku"
            ).to_dict()
        },
    )
    graph.add_edge(src, sink)
    project = tmp_path / "p.prospectra"
    with ProjectStore.create(project) as store:
        store.save_flow("push", graph.to_doc())
    return project, sink


def test_run_flow_with_a_rest_write_exits_2_and_names_the_node(tmp_path, capsys):
    project, sink = _write_flow_project(tmp_path)
    assert main(["run-flow", str(project), "push"]) == 2
    err = capsys.readouterr().err
    assert sink in err  # the node is NAMED
    assert "Nothing was run" in err
    assert "--allow-writes" in err and "--dry-run" in err


def test_run_flow_dry_run_rehearses_a_rest_write_without_a_network(tmp_path, capsys):
    project, _sink = _write_flow_project(tmp_path)
    assert main(["run-flow", str(project), "push", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "dry run" in out
    assert "0 requests sent" in out  # the note reached the terminal, not a logger


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


# 2026-07-31 (P7): `api-send` — a saved playground request replayed headless. The fixture is a
# file:// URL, so CI exercises the whole send path (document → validate → send → print) offline.
def test_api_send_replays_a_saved_request(tmp_path, capsys):
    import json

    body = tmp_path / "orders.json"
    body.write_text('{"orders": [{"id": 1}]}', encoding="utf-8")
    request_doc = tmp_path / "request.json"
    request_doc.write_text(
        json.dumps({"request_schema": 1, "method": "GET", "url": body.as_uri()}),
        encoding="utf-8",
    )
    assert main(["api-send", str(request_doc)]) == 0
    out = capsys.readouterr().out
    assert "HTTP 200" in out
    assert '"orders"' in out


def test_api_send_reports_a_bad_request_document(tmp_path, capsys):
    request_doc = tmp_path / "request.json"
    request_doc.write_text('{"request_schema": 1, "url": ""}', encoding="utf-8")
    assert main(["api-send", str(request_doc)]) == 1
    assert "needs a URL" in capsys.readouterr().err


# 2026-07-31 (P7): the field mapper, headless — the whole chain (document → compile → execute →
# confess losses) drivable from CI with no UI.
def test_map_applies_a_mapping_and_confesses_what_it_lost(tmp_path, capsys):
    import json

    source = tmp_path / "vendor.csv"
    source.write_text(
        "prod_nm,colorway,price_raw\nOxford Shirt,Navy,12.50\nChore Coat,Olive,n/a\n",
        encoding="utf-8",
    )
    doc = {
        "mapping_doc_schema": 1,
        "name": "vendor_to_pim",
        "target_columns": [
            {"name": "styleDescription", "type": "VARCHAR", "required": True},
            {"name": "retailPrice", "type": "DECIMAL(18,4)"},
        ],
        "fields": [
            {
                "target": "styleDescription",
                "sources": ["prod_nm", "colorway"],
                "join_with": " - ",
                "steps": [{"key": "truncate", "args": {"length": 40}}],
            },
            {
                "target": "retailPrice",
                "sources": ["price_raw"],
                "steps": [{"key": "trim", "args": {}}],
            },
        ],
        "unmapped_policy": "drop",
    }
    doc_path = tmp_path / "mapping.json"
    doc_path.write_text(json.dumps(doc), encoding="utf-8")
    out = tmp_path / "pim.csv"

    assert main(["map", "--source", str(source), "--doc", str(doc_path), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "2 rows" in printed
    assert "1 row(s) could not be read as retailPrice" in printed  # 'n/a' — stated, not silent
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "styleDescription,retailPrice"
    assert lines[1] == "Oxford Shirt - Navy,12.5000"


def test_map_names_a_missing_source_column(tmp_path, capsys):
    import json

    source = tmp_path / "vendor.csv"
    source.write_text("a\n1\n", encoding="utf-8")
    doc_path = tmp_path / "mapping.json"
    doc_path.write_text(
        json.dumps(
            {
                "mapping_doc_schema": 1,
                "name": "m",
                "target_columns": [{"name": "x"}],
                "fields": [{"target": "x", "sources": ["gone"]}],
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "map",
                "--source",
                str(source),
                "--doc",
                str(doc_path),
                "--out",
                str(tmp_path / "o.csv"),
            ]
        )
        == 1
    )
    assert "gone" in capsys.readouterr().err


# 2026-08-05: a file-backed crosswalk works headless. It used to die with "Table with name
# xwalk_… does not exist" because only the flow node materialized it — half the crosswalk feature
# existed only inside the GUI. Everything the load had to do to the file is stated.
def test_map_runs_a_file_backed_crosswalk_and_confesses_what_it_did(tmp_path, capsys):
    import json

    source = tmp_path / "feed.csv"
    source.write_text("clr\nNavy\nOlive\nTeal\n", encoding="utf-8")
    xwalk = tmp_path / "colours.csv"
    xwalk.write_text("from,to\nNavy,NVY\nNavy,NAVY\nOlive,OLV\n,ORPHAN\n", encoding="utf-8")
    doc = tmp_path / "doc.json"
    doc.write_text(
        json.dumps(
            {
                "mapping_doc_schema": 1,
                "name": "m",
                "target_columns": [{"name": "colorCode", "type": "VARCHAR"}],
                "fields": [
                    {
                        "target": "colorCode",
                        "sources": ["clr"],
                        "steps": [{"key": "lookup", "args": {"pairs": [], "file": str(xwalk)}}],
                    }
                ],
                "unmapped_policy": "drop",
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out.csv"
    assert main(["map", "--source", str(source), "--doc", str(doc), "--out", str(out)]) == 0

    assert out.read_text(encoding="utf-8").splitlines()[1:] == ["NAVY", "OLV", "Teal"]
    printed = capsys.readouterr().out
    assert "no translation for colorCode" in printed  # Teal
    assert "have no key and were skipped" in printed  # the blank row
    assert "duplicate key" in printed  # the repeated Navy


def test_suggest_map_prints_the_expected_pair(tmp_path, capsys):
    source = tmp_path / "vendor.csv"
    source.write_text("prod_nm,qty\nShirt,4\n", encoding="utf-8")
    target = tmp_path / "pim.csv"
    target.write_text("productName,quantity\nCoat,2\n", encoding="utf-8")

    assert main(["suggest-map", "--source", str(source), "--target", str(target)]) == 0
    printed = capsys.readouterr().out
    assert "prod_nm" in printed and "productName" in printed
    assert "qty" in printed and "quantity" in printed
    assert "nothing is applied for you" in printed  # suggestions are proposals, never actions


def test_scrape_reports_a_page_with_no_tables_instead_of_writing_junk(tmp_path, capsys):
    page = tmp_path / "empty.html"
    page.write_text("<html><body><p>Nothing tabular here.</p></body></html>", encoding="utf-8")
    assert main(["scrape", str(page), "--out", str(tmp_path / "out"), "--tables-only"]) == 1
    assert "No data tables found" in capsys.readouterr().err
