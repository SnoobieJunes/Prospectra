# 2026-07-13 (P1): Generic SQLAlchemy connector — one implementation covers every database with a
# SQLAlchemy dialect (SQLite built-in; Postgres/MySQL/SQL Server/warehouses via optional driver
# extras). Tables are fetched through the dialect and materialized as DuckDB tables.
# Why: this is the plan's T1/T2 mechanism — breadth by URL now, per-dialect connection forms
# later. Honesty: only SQLite is exercised by our tests, so everything else reports
# "experimental" until run against real credentials.

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import duckdb

from prospectra.core.connectors.base import Connector, ConnectorError, ConnectorStatus, DatasetRef


class SQLAlchemyConnector(Connector):
    type_name = "sqlalchemy"
    display_name = "Database (SQLAlchemy URL)"
    status: ClassVar = "experimental"  # per-instance effective status via `effective_status`

    def __init__(self, url: str) -> None:
        from sqlalchemy import create_engine

        self.url = url
        try:
            self._engine = create_engine(url)
        except Exception as exc:  # bad URL / missing driver package
            raise ConnectorError(f"Could not create engine for {url!r}: {exc}") from exc

    @property
    def effective_status(self) -> ConnectorStatus:
        # SQLite is covered by our test suite; every other dialect is untested here.
        return "verified" if self._engine.dialect.name == "sqlite" else "experimental"

    def test_connection(self) -> None:
        from sqlalchemy import text

        # 2026-07-14 (P6): SQLite CREATES a database when asked to open one that is not there, so a
        # typo in a path "connects" successfully to a brand-new empty file and the user is left
        # staring at a source with no tables, with nothing having gone wrong. (This is exactly what
        # a mis-quoted URL did during the P6 acceptance run.) A file database that does not exist
        # is a mistake, not a new project — say so.
        if self._engine.dialect.name == "sqlite":
            database = self._engine.url.database
            if database and database != ":memory:" and not Path(database).is_file():
                raise ConnectorError(
                    f"No database file at {database}. SQLite would silently create an empty one — "
                    "check the path."
                )

        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:
            raise ConnectorError(f"Connection test failed: {exc}") from exc

    def list_datasets(self) -> list[DatasetRef]:
        from sqlalchemy import inspect

        try:
            inspector = inspect(self._engine)
            names = list(inspector.get_table_names()) + list(inspector.get_view_names())
        except Exception as exc:
            raise ConnectorError(f"Could not list tables: {exc}") from exc
        return [DatasetRef(name=n, kind="table") for n in sorted(names)]

    def install(self, cursor: duckdb.DuckDBPyConnection, ref: DatasetRef, view_name: str) -> None:
        import pandas as pd

        try:
            frame = pd.read_sql_table(ref.name, self._engine)
        except Exception as exc:
            raise ConnectorError(f"Could not fetch table {ref.name!r}: {exc}") from exc
        cursor.register("_prospectra_tmp_frame", frame)
        try:
            cursor.execute(
                f"CREATE OR REPLACE TABLE {view_name} AS SELECT * FROM _prospectra_tmp_frame"
            )
        finally:
            cursor.unregister("_prospectra_tmp_frame")

    def close(self) -> None:
        self._engine.dispose()
