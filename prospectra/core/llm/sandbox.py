# 2026-07-13 (P4): The query sandbox — a separate DuckDB database that contains ONLY the datasets
# the user exposed to the assistant, with external access switched off and the configuration
# locked.
#
# Why not just run the model's SQL on the main connection: a plain "SELECT-only" check is not a
# security boundary. `SELECT * FROM read_csv('/etc/passwd')` is a SELECT. So the model gets its
# own database that physically cannot reach the filesystem — verified: read_csv, reading a bare
# path, ATTACH, and re-enabling external access all raise PermissionException/InvalidInputException
# inside it. Rows are copied in (capped) before the lock goes on, so the model can query them and
# nothing else.

from __future__ import annotations

import logging
from dataclasses import dataclass

import duckdb

from prospectra.core.catalog import Catalog
from prospectra.core.sampling import sample_rel
from prospectra.core.sqlutil import ident

logger = logging.getLogger(__name__)

MAX_ROWS_PER_DATASET = 50_000
DEFAULT_SEED = 42


@dataclass(frozen=True)
class SandboxTable:
    dataset_id: str
    table: str  # the name the model sees
    rows: int
    sampled: bool


class QuerySandbox:
    """An isolated DuckDB holding copies of the exposed datasets. Read-only by construction."""

    def __init__(
        self,
        catalog: Catalog,
        dataset_ids: list[str],
        max_rows: int = MAX_ROWS_PER_DATASET,
        seed: int = DEFAULT_SEED,
    ) -> None:
        self._con = duckdb.connect()  # fresh, empty, separate from the catalog's session
        self.tables: dict[str, SandboxTable] = {}

        source = catalog.cursor()
        for dataset_id in dataset_ids:
            dataset = catalog.datasets[dataset_id]
            table = _safe_table_name(dataset.name, len(self.tables))
            total_row = source.execute(f"SELECT count(*) FROM {dataset.view_name}").fetchone()
            total = int(total_row[0]) if total_row else 0
            sampled = total > max_rows
            rel = sample_rel(dataset.view_name, max_rows, seed) if sampled else dataset.view_name
            # Copy the rows in while external access is still permitted (a DataFrame scan needs
            # it) — the lock below is what makes the sandbox airtight afterwards.
            frame = source.execute(f"SELECT * FROM {rel}").df()
            self._con.register("_incoming", frame)
            self._con.execute(f"CREATE TABLE {ident(table)} AS SELECT * FROM _incoming")
            self._con.unregister("_incoming")
            self.tables[table] = SandboxTable(
                dataset_id=dataset_id,
                table=table,
                rows=min(total, max_rows),
                sampled=sampled,
            )

        # …then slam the door. From here the model's SQL cannot touch a file, attach a database,
        # or turn either of those back on.
        self._con.execute("SET enable_external_access=false")
        self._con.execute("SET lock_configuration=true")
        logger.info(
            "Query sandbox ready with %d table(s), external access disabled", len(self.tables)
        )

    def execute(self, sql: str) -> tuple[list[str], list[tuple[object, ...]]]:
        cursor = self._con.cursor()
        cursor.execute(sql)
        columns = [d[0] for d in cursor.description or []]
        return columns, cursor.fetchall()

    def schema(self) -> dict[str, list[tuple[str, str]]]:
        out: dict[str, list[tuple[str, str]]] = {}
        for table in self.tables:
            rows = self._con.execute(f"DESCRIBE SELECT * FROM {ident(table)} LIMIT 0").fetchall()
            out[table] = [(str(r[0]), str(r[1])) for r in rows]
        return out

    def close(self) -> None:
        self._con.close()


def _safe_table_name(name: str, index: int) -> str:
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in name).strip("_").lower()
    return cleaned or f"dataset_{index}"
