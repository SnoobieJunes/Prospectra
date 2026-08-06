# 2026-07-31 (P7): Output owns its own write — the COPY that used to be hard-coded in the runner
# moved here, so the runner can treat every destination (file, catalog table, REST) identically.
# 2026-07-13 (P2): Output — materializes its input to CSV or Parquet. The node compiles to a
# pass-through SELECT; the runner wraps it in COPY so previewing an output shows its data.

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import duckdb

from prospectra.core.flow.node import Node, ParamField, register
from prospectra.core.flow.write import WriteReport
from prospectra.core.sqlutil import path_lit


@register
class OutputNode(Node):
    type_name = "output"
    display_name = "Output"
    category = "output"
    params_schema: ClassVar = (
        ParamField("path", "Write to file", "path", help="Destination .csv or .parquet path"),
        ParamField("format", "Format", "choice", "csv", ("csv", "parquet")),
    )

    def validate(self) -> None:
        if not str(self.params.get("path", "")).strip():
            raise ValueError("set the output file path")

    def compile(self, inputs: list[str]) -> str:
        return f"SELECT * FROM {inputs[0]}"

    def write(
        self, con: duckdb.DuckDBPyConnection, sql: str, *, dry_run: bool = True
    ) -> WriteReport:
        out_path = Path(str(self.params.get("path", "")).strip())
        fmt = str(self.params.get("format", "csv")).lower()
        if dry_run:
            row = con.execute(f"SELECT count(*) FROM ({sql})").fetchone()
            count = int(row[0]) if row else 0
            return WriteReport(
                attempted=count,
                skipped=count,
                dry_run=True,
                path=str(out_path),
                notes=[f"dry run: {count:,} row(s) would be written to {out_path} — none were"],
            )
        options = "FORMAT PARQUET" if fmt == "parquet" else "FORMAT CSV, HEADER"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        row = con.execute(f"COPY ({sql}) TO {path_lit(out_path)} ({options})").fetchone()
        # DuckDB 1.5 quirk: COPY normally returns the number of rows written, but returns an
        # EMPTY result when the query contains a PIVOT (the file is still written correctly).
        # Read the count back off the written file in that case — cheaper and more honest than
        # re-running the whole pipeline to count it.
        written = int(row[0]) if row else self._count_file(con, out_path, fmt)
        return WriteReport(attempted=written, written=written, path=str(out_path))

    @staticmethod
    def _count_file(con: duckdb.DuckDBPyConnection, path: Path, fmt: str) -> int:
        reader = "read_parquet" if fmt == "parquet" else "read_csv_auto"
        row = con.execute(f"SELECT count(*) FROM {reader}({path_lit(path)})").fetchone()
        return int(row[0]) if row else 0
