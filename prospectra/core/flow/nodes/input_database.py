# 2026-07-14 (P6): Input: Database — a flow can now start from a database table or a SQL query,
# not only from a file. This is what makes the P6 acceptance line ("install a dialect, connect, run
# a flow end-to-end") true rather than aspirational: before this, a warehouse you had connected to
# was a dead end as far as the prep canvas was concerned.
#
# It works through the Node.prepare() hook: the rows are fetched with SQLAlchemy and materialized
# into the run's DuckDB connection, and the node then compiles to a plain SELECT over that table.
# The compiler still turns the whole graph into a single CTE query.
#
# The URL is a *reference*, not a secret store: it is saved in the flow document, so a password
# typed into it lands in the project file. The node says so, and the honest path is a URL whose
# credential comes from the environment or from a connection whose secret lives in the OS keychain.

from __future__ import annotations

import hashlib
from typing import ClassVar

import duckdb

from prospectra.core.flow.node import Node, ParamField, register


@register
class InputDatabaseNode(Node):
    type_name = "input_database"
    display_name = "Input: Database"
    category = "input"
    min_inputs = 0
    max_inputs = 0
    params_schema: ClassVar = (
        ParamField(
            "url",
            "Database URL",
            "string",
            help="SQLAlchemy URL, e.g. sqlite:///C:/data/sales.db  (avoid embedding a password)",
        ),
        ParamField(
            "table", "Table", "string", help="Table name — or leave blank and write a query"
        ),
        ParamField("query", "SQL query (optional)", "expression", help="Overrides Table when set"),
    )

    def validate(self) -> None:
        if not str(self.params.get("url", "")).strip():
            raise ValueError("set the database URL")
        if (
            not str(self.params.get("table", "")).strip()
            and not str(self.params.get("query", "")).strip()
        ):
            raise ValueError("name a table, or write a query")

    @property
    def _relation(self) -> str:
        """A deterministic name for the materialized table, so re-runs reuse it predictably."""
        seed = f"{self.params.get('url')}|{self.params.get('table')}|{self.params.get('query')}"
        return "src_" + hashlib.sha1(seed.encode()).hexdigest()[:12]

    def prepare(self, con: duckdb.DuckDBPyConnection) -> None:
        import pandas as pd
        from sqlalchemy import create_engine, text

        from prospectra.core.connectors.base import ConnectorError

        url = str(self.params["url"]).strip()
        query = str(self.params.get("query", "")).strip()
        table = str(self.params.get("table", "")).strip()
        try:
            engine = create_engine(url)
        except Exception as exc:  # a missing driver package lands here
            raise ConnectorError(f"Could not open {url}: {exc}") from exc
        try:
            with engine.connect() as connection:
                if query:
                    frame = pd.read_sql_query(text(query), connection)
                else:
                    frame = pd.read_sql_table(table, connection)
        except Exception as exc:  # bad credentials, bad SQL, unreachable server
            raise ConnectorError(f"Could not read from {url}: {exc}") from exc
        finally:
            engine.dispose()

        con.register("_prospectra_tmp_db", frame)
        try:
            con.execute(
                f"CREATE OR REPLACE TABLE {self._relation} AS SELECT * FROM _prospectra_tmp_db"
            )
        finally:
            con.unregister("_prospectra_tmp_db")

    def compile(self, inputs: list[str]) -> str:
        return f"SELECT * FROM {self._relation}"
