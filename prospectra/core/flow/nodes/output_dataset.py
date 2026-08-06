# 2026-07-31 (P7): Output: Local Dataset — CREATE OR REPLACE TABLE into a DuckDB database FILE.
#
# Why a file and not the session catalog: a flow run executes on its own isolated connection
# (the P2 reproducibility rule), so a table created "in the catalog" would evaporate with the
# run's connection. A .duckdb file is durable and headless-friendly, and CREATE OR REPLACE is the
# point (an upsert-style refresh of a named local table). `destructive` stays False: this touches
# only a local file the user named, never someone else's system.
#
# HONEST LIMIT (2026-08-05): Prospectra cannot currently re-open what this writes. `_READERS`
# covers csv/tsv/txt/json/jsonl/ndjson/parquet, and there is no DuckDB dialect in DIALECTS, so the
# file is readable by the DuckDB CLI or another tool but not by this app's own Open File / Add
# Database paths. Use the CSV/Parquet Output node if you need the result back inside Prospectra.
# Tracked in Deviations.md.

from __future__ import annotations

import re
from typing import ClassVar

import duckdb

from prospectra.core.flow.node import Node, ParamField, register
from prospectra.core.flow.write import WriteReport
from prospectra.core.sqlutil import ident, path_lit

_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@register
class OutputDatasetNode(Node):
    type_name = "output_dataset"
    display_name = "Output: Local Dataset"
    category = "output"
    params_schema: ClassVar = (
        ParamField(
            "database",
            "Database file",
            "path",
            help="A .duckdb file (created if missing). Note: Prospectra cannot re-open a .duckdb "
            "file yet — use the CSV/Parquet Output node if you need the result back in the app.",
        ),
        ParamField(
            "table",
            "Table name",
            "string",
            "mapped",
            help="CREATE OR REPLACE TABLE under this name — re-running refreshes it",
        ),
    )

    def validate(self) -> None:
        if not str(self.params.get("database", "")).strip():
            raise ValueError("set the database file path")
        table = str(self.params.get("table", "")).strip()
        if not _TABLE_NAME.match(table):
            raise ValueError(
                "the table name must be letters/digits/underscores, starting with a letter"
            )

    def compile(self, inputs: list[str]) -> str:
        return f"SELECT * FROM {inputs[0]}"

    def write(
        self, con: duckdb.DuckDBPyConnection, sql: str, *, dry_run: bool = True
    ) -> WriteReport:
        database = str(self.params["database"]).strip()
        table = ident(str(self.params["table"]).strip())
        if dry_run:
            row = con.execute(f"SELECT count(*) FROM ({sql})").fetchone()
            count = int(row[0]) if row else 0
            return WriteReport(
                attempted=count,
                skipped=count,
                dry_run=True,
                path=database,
                notes=[
                    f"dry run: {count:,} row(s) would become table "
                    f"{self.params['table']} in {database} — nothing was written"
                ],
            )
        con.execute(f"ATTACH {path_lit(database)} AS _p7_dest")
        try:
            con.execute(f"CREATE OR REPLACE TABLE _p7_dest.{table} AS {sql}")
            row = con.execute(f"SELECT count(*) FROM _p7_dest.{table}").fetchone()
            written = int(row[0]) if row else 0
        finally:
            con.execute("DETACH _p7_dest")
        return WriteReport(attempted=written, written=written, path=database)
