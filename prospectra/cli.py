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

    scan = sub.add_parser("scan", help="Mine a dataset for relationships (arrives in phase P3)")
    scan.add_argument("path", help="Dataset file to scan")
    scan.add_argument("--target", help="Target column to explain (e.g. sales)")

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
        print(
            "prospectra scan: not implemented yet — the mining engine lands in phase P3.",
            file=sys.stderr,
        )
        return 2
    if args.command == "run-flow":
        return _run_flow(args.project, args.flow)
    if args.command == "generate-example":
        from prospectra.example_data import write_csv

        path = write_csv(Path(args.out), days=args.days, seed=args.seed)
        print(f"Wrote {path}")
        return 0

    from prospectra.app import run_gui  # deferred: keeps headless use Qt-free

    return run_gui(smoke=args.smoke)


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
