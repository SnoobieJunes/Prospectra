# 2026-07-13 (P1): The Catalog — one in-memory DuckDB session per app, holding every opened
# dataset as a view (files) or table (materialized sources), plus registered SQL connections.
# Why: a single analytical session lets the grid, profiler, and (later) flows and the mining
# engine query any opened dataset uniformly. Thread model: the root connection only spawns
# cursors; every operation (including from QThreadPool workers) runs on its own cursor, which is
# DuckDB's supported multi-threading pattern. Views/tables are session-wide, so cursors see them.

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

import duckdb

from prospectra.core.connectors.base import ConnectorStatus, DatasetRef
from prospectra.core.connectors.registry import file_connector_for
from prospectra.core.connectors.sql_alchemy import SQLAlchemyConnector
from prospectra.core.stats import TableProfile, profile_relation

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Dataset:
    id: str
    name: str  # display name, e.g. "orders" or "workbook · Sheet1"
    view_name: str  # DuckDB view/table identifier
    origin: str  # human-readable provenance, e.g. a file path or "db: sales.orders"


@dataclass(frozen=True)
class SqlConnection:
    id: str
    name: str
    url: str
    status: ConnectorStatus


class Catalog:
    def __init__(self) -> None:
        self._con = duckdb.connect()  # in-memory analytical session
        self._counter = 0
        self.datasets: dict[str, Dataset] = {}
        self.connections: dict[str, SqlConnection] = {}
        self._connectors: dict[str, SQLAlchemyConnector] = {}  # connection id -> live connector

    # -- session ---------------------------------------------------------------------

    def cursor(self) -> duckdb.DuckDBPyConnection:
        """A fresh cursor; safe to use from a worker thread (one cursor per thread)."""
        return self._con.cursor()

    def close(self) -> None:
        for connector in self._connectors.values():
            connector.close()
        self._con.close()

    def _next_view(self) -> str:
        self._counter += 1
        return f"ds_{self._counter}"

    # -- files -----------------------------------------------------------------------

    def open_file(self, path: Path | str) -> list[Dataset]:
        """Open a data file (or every sheet of a workbook) as dataset(s)."""
        p = Path(path)
        connector = file_connector_for(p)
        cur = self.cursor()
        opened: list[Dataset] = []
        for ref in connector.list_datasets():
            view = self._next_view()
            connector.install(cur, ref, view)
            display = p.stem if ref.kind == "file" else f"{p.stem} · {ref.name}"
            ds = Dataset(id=uuid.uuid4().hex, name=display, view_name=view, origin=str(p))
            self.datasets[ds.id] = ds
            opened.append(ds)
            logger.info("Opened dataset %s from %s", display, p)
        return opened

    # -- SQL connections ---------------------------------------------------------------

    def add_connection(self, name: str, url: str) -> SqlConnection:
        """Register a database by SQLAlchemy URL and verify it answers a ping."""
        connector = SQLAlchemyConnector(url)
        connector.test_connection()
        conn = SqlConnection(
            id=uuid.uuid4().hex, name=name, url=url, status=connector.effective_status
        )
        self.connections[conn.id] = conn
        self._connectors[conn.id] = connector
        logger.info("Added connection %s (%s, %s)", name, connector.effective_status, url)
        return conn

    def list_tables(self, connection_id: str) -> list[str]:
        return [ref.name for ref in self._connectors[connection_id].list_datasets()]

    def open_table(self, connection_id: str, table: str) -> Dataset:
        connector = self._connectors[connection_id]
        conn = self.connections[connection_id]
        view = self._next_view()
        connector.install(self.cursor(), DatasetRef(name=table, kind="table"), view)
        ds = Dataset(
            id=uuid.uuid4().hex,
            name=table,
            view_name=view,
            origin=f"db: {conn.name}.{table}",
        )
        self.datasets[ds.id] = ds
        logger.info("Opened table %s from connection %s", table, conn.name)
        return ds

    # -- queries used by the grid & profiler ------------------------------------------

    def describe(self, dataset_id: str) -> list[tuple[str, str]]:
        ds = self.datasets[dataset_id]
        rows = self.cursor().execute(f"DESCRIBE SELECT * FROM {ds.view_name} LIMIT 0").fetchall()
        return [(str(r[0]), str(r[1])) for r in rows]

    def count_rows(self, dataset_id: str) -> int:
        ds = self.datasets[dataset_id]
        row = self.cursor().execute(f"SELECT count(*) FROM {ds.view_name}").fetchone()
        return int(row[0]) if row else 0

    def fetch_page(self, dataset_id: str, offset: int, limit: int) -> list[tuple[object, ...]]:
        ds = self.datasets[dataset_id]
        return (
            self.cursor()
            .execute(f"SELECT * FROM {ds.view_name} LIMIT {int(limit)} OFFSET {int(offset)}")
            .fetchall()
        )

    def profile(self, dataset_id: str, *, max_rows: int = 50_000) -> TableProfile:
        ds = self.datasets[dataset_id]
        return profile_relation(self.cursor(), ds.view_name, max_rows=max_rows)
