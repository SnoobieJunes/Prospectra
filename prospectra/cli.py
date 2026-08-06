# 2026-07-14 (P6): `connectors` — print every connector, dialect, and LLM provider with its honest
# status badge and whether its driver is installed. One command answers "what can this actually talk
# to, right now, on this machine?" — which is exactly the question the badges exist to answer.
# 2026-07-14 (P5): `scrape` — fetch a page (robots.txt obeyed, per-host rate limited), extract its
# tables, and write them as CSVs that any flow or scan can read. Accepts a local .html path or a
# file:// URL too, which is how CI exercises the whole scrape path with no network.
# 2026-07-13 (P3): `scan` is now real — mines a data file for relationships and prints the ranked
# table headless (the P3 acceptance path; also how CI exercises the whole stats engine).
# 2026-07-13 (P2): `run-flow` is now real — opens a project, loads a flow by name or id, and
# executes its Output nodes headless (the P2 acceptance path and the CI workhorse).
# 2026-07-13 (P0): Entry point — GUI by default, headless subcommands for CI and power users.
# Why: the build plan requires the whole engine to be drivable without a display; the GUI import
# is deferred so headless commands never touch Qt. `scan` stays an honest stub (exit 2) until P3.

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from prospectra import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="prospectra",
        description="Prospectra — your data buddy. Run with no arguments to launch the GUI.",
    )
    parser.add_argument("--version", action="version", version=f"prospectra {__version__}")
    # Hidden CI flag: launch the real GUI, auto-quit after ~2.5 s (used to verify launch).
    parser.add_argument("--smoke", action="store_true", help=argparse.SUPPRESS)

    sub = parser.add_subparsers(dest="command")

    scan = sub.add_parser("scan", help="Mine a dataset for relationships")
    scan.add_argument("path", help="Dataset file to scan")
    scan.add_argument("--target", help="Target column to explain (e.g. sales)")
    scan.add_argument("--max-rows", type=int, default=50_000, help="Sample size cap")
    scan.add_argument("--seed", type=int, default=42, help="Sample seed (reproducibility)")
    scan.add_argument("--alpha", type=float, default=0.05, help="FDR level (default 0.05)")
    scan.add_argument("--pca", action="store_true", help="Also print the PCA narrative")

    run_flow = sub.add_parser("run-flow", help="Run a saved prep flow headless")
    run_flow.add_argument("project", help="Path to a .prospectra project file")
    run_flow.add_argument("flow", help="Flow name or id")
    # 2026-07-31 (P7): a flow containing a live write (REST) refuses to run without --allow-writes
    # — it exits 2 and names the node. Silently skipping it would be worse: the user believes the
    # flow ran. --dry-run rehearses every output (counts, validates, sends nothing).
    run_flow.add_argument(
        "--allow-writes",
        action="store_true",
        help="Permit output nodes that write to external systems (live API writes)",
    )
    run_flow.add_argument(
        "--dry-run",
        action="store_true",
        help="Rehearse every output: count and validate, write nothing",
    )
    run_flow.add_argument(
        "--failures-csv",
        help="Write failed rows (index, key, status, message) to this CSV for manual recovery",
    )

    scrape = sub.add_parser("scrape", help="Scrape a web page's tables into CSV files")
    scrape.add_argument("url", help="Page URL (http/https), or a local .html file to re-parse")
    scrape.add_argument("--out", default="scraped", help="Folder for the CSVs (default: ./scraped)")
    scrape.add_argument(
        "--tables-only",
        action="store_true",
        help="Fail if the page has no tables (instead of saving its article text)",
    )
    scrape.add_argument("--max-tables", type=int, help="Keep only the first N tables")

    sub.add_parser(
        "connectors", help="List every connector, database dialect, and LLM provider + its status"
    )

    # 2026-07-31 (P7): replay a saved playground request headless. file:// URLs are served from
    # disk, which is how CI exercises the whole send path with no network.
    api_send = sub.add_parser("api-send", help="Send a saved HTTP request and print the response")
    api_send.add_argument("request", help="Path to a request .json saved from the API playground")
    api_send.add_argument(
        "--secret-ref", help="OS-keychain entry holding the request's auth credential"
    )

    # 2026-07-31 (P7): the field mapper, headless — apply a saved mapping document to a file.
    map_cmd = sub.add_parser("map", help="Apply a field-mapping document to a dataset")
    map_cmd.add_argument("--source", required=True, help="Input data file (CSV/JSON/Parquet…)")
    map_cmd.add_argument("--doc", required=True, help="MappingDoc .json")
    map_cmd.add_argument("--out", required=True, help="Output .csv path")

    suggest = sub.add_parser(
        "suggest-map", help="Suggest source→target column matches between two datasets"
    )
    suggest.add_argument("--source", required=True, help="Source data file")
    suggest.add_argument("--target", required=True, help="Target data file (its columns)")

    gen = sub.add_parser(
        "generate-example", help="Write the synthetic ice-cream tutorial dataset (seeded)"
    )
    gen.add_argument("out", nargs="?", default="examples/ice_cream_sales.csv")
    gen.add_argument("--days", type=int, default=1095)
    gen.add_argument("--seed", type=int, default=42)

    args = parser.parse_args(argv)

    if args.command == "scan":
        return _scan(args.path, args.target, args.max_rows, args.seed, args.alpha, args.pca)
    if args.command == "run-flow":
        return _run_flow(
            args.project, args.flow, args.allow_writes, args.dry_run, args.failures_csv
        )
    if args.command == "scrape":
        return _scrape(args.url, args.out, args.tables_only, args.max_tables)
    if args.command == "connectors":
        return _connectors()
    if args.command == "api-send":
        return _api_send(args.request, args.secret_ref)
    if args.command == "map":
        return _map(args.source, args.doc, args.out)
    if args.command == "suggest-map":
        return _suggest_map(args.source, args.target)
    if args.command == "generate-example":
        from prospectra.example_data import write_csv

        path = write_csv(Path(args.out), days=args.days, seed=args.seed)
        print(f"Wrote {path}")
        return 0

    from prospectra.app import run_gui  # deferred: keeps headless use Qt-free

    return run_gui(smoke=args.smoke)


def _scan(
    path: str, target: str | None, max_rows: int, seed: int, alpha: float, show_pca: bool
) -> int:
    from prospectra.core.catalog import Catalog
    from prospectra.core.connectors import ConnectorError, UnsupportedFileError
    from prospectra.core.mining import scan_relation

    catalog = Catalog()
    try:
        try:
            datasets = catalog.open_file(path)
        except (ConnectorError, UnsupportedFileError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        dataset = datasets[0]
        try:
            result = scan_relation(
                catalog.cursor(),
                dataset.view_name,
                target=target,
                max_rows=max_rows,
                seed=seed,
                alpha=alpha,
                dataset_name=dataset.name,
            )
        except ValueError as exc:  # bad target
            print(f"error: {exc}", file=sys.stderr)
            return 1

        print(f"\n{result.dataset}: {result.summary}\n")
        if result.roles.excluded:
            for column, reason in result.roles.excluded.items():
                print(f"  skipped {column}: {reason}")
            print()

        if result.drivers:
            print(f"WHAT EXPLAINS {target} (each variable on its own, best-fitting form)")
            print(f"  {'variable':<20} {'adj R²':>8} {'R²':>8} {'form':<11} {'p':>10}")
            for fit in result.drivers:
                print(
                    f"  {fit.predictor:<20} {fit.adj_r2:>8.3f} {fit.r2:>8.3f} "
                    f"{fit.form:<11} {fit.p_value:>10.2e}"
                )
            print()

        if result.model is not None:
            model = result.model
            print(f"BEST COMBINED MODEL: adj R² = {model.adj_r2:.3f} on {model.n:,} rows")
            ranked = sorted(model.std_coefficients.items(), key=lambda kv: abs(kv[1]), reverse=True)
            for name, std in ranked:
                vif = model.vif.get(name)
                vif_text = f"  VIF {vif:.1f}" if vif is not None else ""
                print(f"  {name:<20} standardized β = {std:+.3f}{vif_text}")
            for note in model.notes:
                print(f"  note: {note}")
            print()

        if result.diagnostics is not None:
            print(f"TRUST: {result.diagnostics.verdict.upper()}")
            for note in result.diagnostics.notes:
                print(f"  {note}")
            print()

        print(f"RELATIONSHIPS (FDR-controlled at q <= {alpha})")
        if not result.findings:
            print("  none survived multiple-testing correction")
        for finding in result.findings:
            if finding.kind in ("driver", "model"):
                continue
            print(
                f"  [{finding.strength:<9}] {finding.title:<34} "
                f"{finding.effect_name} = {finding.effect:.2f}  q = {finding.q_value:.2e}"
            )
            print(f"              {finding.headline}")
        if result.rejected:
            names = ", ".join(f.title for f in result.rejected[:6])
            print(f"\n  rejected by FDR ({len(result.rejected)}): {names}")

        if show_pca and result.pca is not None:
            print("\nPCA")
            print("  " + result.pca.narrative.replace("\n", "\n  "))
        print()
        return 0
    finally:
        catalog.close()


def _scrape(url: str, out: str, tables_only: bool, max_tables: int | None) -> int:
    from prospectra.core.scraper import RobotsDisallowed, ScraperError, scrape

    try:
        result = scrape(url, Path(out), tables_only=tables_only, max_tables=max_tables)
    except RobotsDisallowed as exc:
        print(f"refused: {exc}", file=sys.stderr)  # obeying robots.txt is not a failure to fix
        return 1
    except ScraperError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"\n{result.summary}\n")
    for emitted in result.files:
        print(f"  {emitted.path}  ({emitted.rows:,} rows x {emitted.columns} cols)  {emitted.name}")
    if result.article_path is not None:
        print(f"  {result.article_path}  {result.article_title}")
    print("\nOpen any of these with `prospectra scan <file>` or in the app (Sources ▸ Open File…).")
    return 0


# 2026-07-31 (P7): the playground's headless twin — load a request document, send it, print what
# came back. Non-2xx is *printed as a result* (that is the playground's contract) but exits 1 so
# scripts can branch on success; a transport failure also exits 1 with the error stated.
def _api_send(request_path: str, secret_ref: str | None) -> int:
    import json

    from prospectra.core.http import HttpRequest, redact_headers, send

    try:
        doc = json.loads(Path(request_path).read_text(encoding="utf-8"))
        request = HttpRequest.from_dict(doc)
        request.validate()
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    secret = None
    if secret_ref:
        from prospectra.core.llm import secrets as secret_store

        try:
            secret = secret_store.get_api_key(secret_ref)
        except secret_store.SecretsError as exc:
            print(f"error: could not read the keychain: {exc}", file=sys.stderr)
            return 1
        if not secret:
            print(f"error: no keychain entry named {secret_ref!r}", file=sys.stderr)
            return 1

    response = send(request, secret)
    if response.error:
        print(f"error: {response.error}", file=sys.stderr)
        return 1

    print(
        f"HTTP {response.status} {response.reason}  "
        f"({response.elapsed_ms:.0f} ms, {response.size_bytes:,} bytes)"
    )
    for name, value in redact_headers(response.headers).items():
        print(f"  {name}: {value}")
    if response.text:
        print()
        print(response.text)
    return 0 if response.ok else 1


# 2026-07-31 (P7): file -> reader SQL, shared by `map` and `suggest-map`.
def _file_rel(path_str: str) -> str:
    from prospectra.core.connectors.files import _READERS
    from prospectra.core.sqlutil import path_lit

    path = Path(path_str)
    reader = _READERS.get(path.suffix.lower())
    if reader is None or not path.is_file():
        raise ValueError(f"cannot read {path} (supported: {', '.join(sorted(_READERS))})")
    return f"(SELECT * FROM {reader}({path_lit(path)}))"


def _map(source: str, doc_path: str, out: str) -> int:
    import json

    import duckdb

    from prospectra.core.mapping import (
        MappingDoc,
        coercion_check_sql,
        compile_notes,
        compile_select,
    )
    from prospectra.core.sqlutil import path_lit

    try:
        doc = MappingDoc.from_dict(json.loads(Path(doc_path).read_text(encoding="utf-8")))
        rel = _file_rel(source)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # 2026-08-05: the CLI materializes file-backed crosswalks the same way the flow node does.
    # It never did, so `map` with a crosswalk FILE died on "Table with name xwalk_… does not
    # exist" — half the crosswalk feature worked only inside the GUI, contra the project's rule
    # that engine features get headless coverage.
    from prospectra.core.flow.nodes.map_fields import MapFieldsNode

    node = MapFieldsNode({"doc": doc.to_dict()})

    con = duckdb.connect()
    try:
        try:
            node.prepare(con)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        described = con.execute(f"DESCRIBE SELECT * FROM {rel} LIMIT 0").fetchall()
        available = [str(r[0]) for r in described]
        try:
            sql = compile_select(doc, rel, available=available)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        row = con.execute(f"COPY ({sql}) TO {path_lit(out_path)} (FORMAT CSV, HEADER)").fetchone()
        written = int(row[0]) if row else 0
        print(f"wrote {out_path} ({written} rows)")

        # Nothing is silent: report every value the chain lost and every crosswalk miss.
        check_sql = coercion_check_sql(doc, rel)
        if check_sql:
            counts = con.execute(check_sql).fetchone()
            names = [str(d[0]) for d in con.description or []]
            for name, count in zip(names, counts or (), strict=False):
                if not count:
                    continue
                target, _sep, kind = name.partition("__")
                if kind.startswith("unmatched"):
                    print(f"  note: {count} row(s) had no translation for {target}")
                elif kind.startswith("lost_"):
                    print(
                        f"  note: {count} row(s) could not be read by the "
                        f"{kind[len('lost_') :]} step of {target}"
                    )
                else:
                    print(f"  note: {count} row(s) could not be read as {target}")
        # The node's own confessions (truncated/deduped/blank-key crosswalks) reach the terminal
        # too — they used to exist only on the object and be read by nothing.
        for note in [*node.prepare_notes, *compile_notes(doc)]:
            print(f"  note: {note}")
    except duckdb.Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        con.close()
    return 0


def _suggest_map(source: str, target: str) -> int:
    import duckdb

    from prospectra.core.mapping import suggest_from_values, suggest_matches

    con = duckdb.connect()
    try:
        try:
            source_rel, target_rel = _file_rel(source), _file_rel(target)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        source_cols = [
            (str(r[0]), str(r[1]))
            for r in con.execute(f"DESCRIBE SELECT * FROM {source_rel} LIMIT 0").fetchall()
        ]
        target_cols = [
            (str(r[0]), str(r[1]))
            for r in con.execute(f"DESCRIBE SELECT * FROM {target_rel} LIMIT 0").fetchall()
        ]

        by_name = suggest_matches(source_cols, target_cols)
        print("\nBY NAME (accept, correct, or ignore — nothing is applied for you)")
        if not by_name:
            print("  no name-based matches cleared the confidence bar")
        for s in by_name:
            print(f"  {s.source:<24} -> {s.target:<24} {s.confidence:>5.0%}  {s.reason}")

        # Values for what names couldn't settle: every still-unmatched source/target pair.
        matched_sources = {s.source for s in by_name}
        matched_targets = {s.target for s in by_name}
        pairs = [
            (sc, tc)
            for sc, _ in source_cols
            if sc not in matched_sources
            for tc, _ in target_cols
            if tc not in matched_targets
        ][:400]
        by_values = suggest_from_values(con, source_rel, target_rel, pairs)
        if by_values:
            print("\nBY VALUES (names disagree, the data does not)")
            for s in by_values:
                print(f"  {s.source:<24} -> {s.target:<24} {s.confidence:>5.0%}  {s.reason}")
        print()
    except duckdb.Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        con.close()
    return 0


def _connectors() -> int:
    from prospectra.core.connectors import (
        DIALECTS,
        SUPPORTED_FILE_SUFFIXES,
        external_connectors,
        jdbc_available,
    )
    from prospectra.core.llm import PROVIDERS

    def badge(status: str) -> str:
        return "verified " if status == "verified" else "EXPERIMENTAL"

    print("\nFILES")
    print(f"  {', '.join(SUPPORTED_FILE_SUFFIXES)}")
    print("  (.pdf needs `uv sync --extra pdf`; .sav/.dta/.sas7bdat need `--extra stats-files`)")

    print("\nDATABASES (one generic SQLAlchemy connector; these are the forms it knows)")
    print(f"  {'dialect':<26} {'status':<13} driver")
    for dialect in DIALECTS:
        driver = (
            "built in"
            if not dialect.driver_package
            else (
                "installed" if dialect.driver_installed else f"MISSING — {dialect.install_hint()}"
            )
        )
        print(f"  {dialect.display_name:<26} {badge(dialect.status):<13} {driver}")
    print(
        f"  {'Generic JDBC':<26} {'EXPERIMENTAL':<13} "
        f"{'installed' if jdbc_available() else 'MISSING — uv sync --extra jdbc (needs a JVM)'}"
    )

    print("\nAPIs")
    print(f"  {'REST / OData (mapping)':<26} {'EXPERIMENTAL':<13} built in")

    plugins = external_connectors()
    print("\nPLUGINS (installed, via the prospectra.connectors entry point)")
    if not plugins:
        print("  (none)")
    for name, cls in sorted(plugins.items()):
        print(f"  {cls.display_name:<26} {badge(cls.status):<13} {name}")

    print("\nLLM PROVIDERS")
    for provider in PROVIDERS.values():
        note = "custom endpoint (URL + key + model)" if provider.supports_custom_endpoint else ""
        status = badge("verified" if provider.verified else "x")
        print(f"  {provider.display_name:<44} {status:<13} {note}")

    print(
        "\nEXPERIMENTAL means: implemented and tested against scripted servers, but never run\n"
        "against a real one from this build. It is not a guess about whether it works — it is a\n"
        "statement that nobody has watched it work.\n"
    )
    return 0


def _run_flow(
    project_path: str,
    flow_ref: str,
    allow_writes: bool = False,
    dry_run: bool = False,
    failures_csv: str | None = None,
) -> int:
    from prospectra.core.flow import FlowError, FlowGraph, FlowRunner
    from prospectra.core.project import ProjectStore, ProjectStoreError

    try:
        store = ProjectStore.open(project_path)
    except ProjectStoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        flows = store.list_flows()
        matches = [f for f in flows if flow_ref in (f.id, f.name)]
        if not matches:
            names = ", ".join(f.name for f in flows) or "(none)"
            print(f"error: no flow {flow_ref!r} in project. Flows: {names}", file=sys.stderr)
            return 1
        try:
            graph = FlowGraph.from_doc(matches[0].doc)
        except FlowError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        # 2026-07-31 (P7): pre-flight — a live write needs explicit consent BEFORE anything runs.
        # Exit 2, naming the node: silently skipping it would leave the user believing it ran.
        if not allow_writes and not dry_run:
            for node_id in graph.output_nodes():
                node = graph.nodes[node_id].node
                if node.destructive:
                    print(
                        f"refused: node {node_id} ({node.display_name}) sends live writes to an "
                        "external system.\nNothing was run. Re-run with --allow-writes to mean "
                        "it, or --dry-run to rehearse.",
                        file=sys.stderr,
                    )
                    return 2

        try:
            results = FlowRunner().run(graph, allow_writes=allow_writes, dry_run=dry_run)
        except FlowError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if not results:
            print("error: flow has no Output nodes — nothing to run", file=sys.stderr)
            return 1
        failed = False
        for result in results:
            if result.dry_run:
                print(f"dry run: {result.path or result.node_id} ({result.attempted} rows)")
            elif result.path:
                print(f"wrote {result.path} ({result.rows} rows)")
            else:
                print(f"{result.node_id}: {result.written} written, {result.failed} failed")
            # notes and failures reach the terminal — they must never die in a logger.
            for note in result.notes:
                print(f"  note: {note}")
            for failure in result.failures[:20]:
                print(
                    f"  failed row {failure.index} ({failure.key or 'no key'}): "
                    f"HTTP {failure.status} {failure.message}"
                )
            if len(result.failures) > 20:
                print(f"  … and {len(result.failures) - 20} more failed row(s)")
            failed = failed or result.failed > 0
        if failures_csv and any(r.failures for r in results):
            from prospectra.core.http.write import write_failures_csv

            merged = results[0]
            for extra in results[1:]:
                merged.failures.extend(extra.failures)
            written_csv = write_failures_csv(merged, failures_csv)
            print(
                f"failed rows written to {written_csv} — fix the cause, then re-run just those "
                "keys (the node's 'Only these keys' setting). Resume is manual."
            )
        return 1 if failed else 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
