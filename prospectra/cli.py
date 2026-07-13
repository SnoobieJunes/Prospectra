# 2026-07-13 (P0): Entry point — GUI by default, headless subcommands for CI and power users.
# Why: the build plan requires the whole engine to be drivable without a display; the GUI import
# is deferred so headless commands never touch Qt. `scan` and `run-flow` are honest stubs (exit 2)
# until their phases (P3 / P2) land — they must not pretend to work.

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

    run_flow = sub.add_parser(
        "run-flow", help="Run a saved prep flow headless (arrives in phase P2)"
    )
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
        print(
            "prospectra run-flow: not implemented yet — the flow engine lands in phase P2.",
            file=sys.stderr,
        )
        return 2
    if args.command == "generate-example":
        from prospectra.example_data import write_csv

        path = write_csv(Path(args.out), days=args.days, seed=args.seed)
        print(f"Wrote {path}")
        return 0

    from prospectra.app import run_gui  # deferred: keeps headless use Qt-free

    return run_gui(smoke=args.smoke)


if __name__ == "__main__":
    raise SystemExit(main())
