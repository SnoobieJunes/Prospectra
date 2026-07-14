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
        return _run_flow(args.project, args.flow)
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


def _run_flow(project_path: str, flow_ref: str) -> int:
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
            results = FlowRunner().run(graph)
        except FlowError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if not results:
            print("error: flow has no Output nodes — nothing to run", file=sys.stderr)
            return 1
        for result in results:
            print(f"wrote {result.path} ({result.rows} rows)")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
