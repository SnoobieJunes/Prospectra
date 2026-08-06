# 2026-07-14 (P5): Dashboards (a P0 schema table, unused until now) get real CRUD, and the project
# gains a staging folder — the place scraped tables land so they become ordinary file datasets.
# 2026-07-13 (P0): The .prospectra project file — a single SQLite database holding connections
# (secret *references* only — actual secrets live in the OS keychain via `keyring`, arriving P4),
# versioned flow documents, findings, and dashboards.
# Why: findings need durable, lineage-friendly storage without a server, and a single file is the
# unit users expect to move around / back up. Schema is versioned from day one so later phases can
# migrate instead of breaking old projects.

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE connections (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    connector_type TEXT NOT NULL,
    config_json    TEXT NOT NULL DEFAULT '{}',
    secret_ref     TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE TABLE flows (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    doc_json   TEXT NOT NULL,
    version    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE findings (
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    title        TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    flow_id      TEXT,
    dataset_ref  TEXT,
    sample_seed  INTEGER,
    created_at   TEXT NOT NULL
);
CREATE TABLE dashboards (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    layout_json TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


class ProjectStoreError(Exception):
    """Base error for project-store failures."""


class ProjectVersionError(ProjectStoreError):
    """Project file was written by a newer Prospectra than this one."""


@dataclass(frozen=True)
class FlowRecord:
    id: str
    name: str
    doc: dict[str, Any]
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DashboardRecord:
    id: str
    name: str
    layout: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ConnectionRecord:
    id: str
    name: str
    connector_type: str
    config: dict[str, Any]
    secret_ref: str | None
    created_at: str
    updated_at: str


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ProjectStore:
    """Open/create and read/write a .prospectra project file.

    Construct via :meth:`create` or :meth:`open`, not directly.
    """

    def __init__(self, path: Path, conn: sqlite3.Connection) -> None:
        self._path = path
        self._conn = conn
        self._conn.row_factory = sqlite3.Row

    # -- lifecycle -----------------------------------------------------------------

    @classmethod
    def create(cls, path: Path | str) -> ProjectStore:
        p = Path(path)
        if p.exists():
            raise ProjectStoreError(f"Refusing to overwrite existing file: {p}")
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(p))
        try:
            conn.executescript(_SCHEMA_V1)
            store = cls(p, conn)
            store.set_meta("schema_version", str(SCHEMA_VERSION))
            store.set_meta("created_at", _now())
            return store
        except BaseException:
            conn.close()
            raise

    @classmethod
    def open(cls, path: Path | str) -> ProjectStore:
        p = Path(path)
        if not p.is_file():
            raise ProjectStoreError(f"No such project file: {p}")
        conn = sqlite3.connect(str(p))
        store = cls(p, conn)
        try:
            raw = store.get_meta("schema_version")
            if raw is None:
                raise ProjectStoreError(f"Not a Prospectra project file: {p}")
            version = int(raw)
        except sqlite3.DatabaseError as exc:
            conn.close()
            raise ProjectStoreError(f"Not a Prospectra project file: {p}") from exc
        except ProjectStoreError:
            conn.close()
            raise
        if version > SCHEMA_VERSION:
            conn.close()
            raise ProjectVersionError(
                f"Project schema v{version} is newer than this app supports (v{SCHEMA_VERSION}). "
                "Update Prospectra to open it."
            )
        return store

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ProjectStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def schema_version(self) -> int:
        raw = self.get_meta("schema_version")
        return int(raw) if raw is not None else 0

    # 2026-07-14 (P5): Scraped tables have to live somewhere the user can find, back up, and open
    # as ordinary files — a sibling folder of the project, not a hidden temp dir that a reboot eats.
    @property
    def staging_dir(self) -> Path:
        """Folder for files this project generated (scraped tables, flow outputs)."""
        staging = self._path.parent / f"{self._path.stem}_files"
        staging.mkdir(parents=True, exist_ok=True)
        return staging

    # -- meta ----------------------------------------------------------------------

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    # -- flows ---------------------------------------------------------------------

    def save_flow(self, name: str, doc: dict[str, Any]) -> FlowRecord:
        now = _now()
        flow_id = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO flows(id, name, doc_json, version, created_at, updated_at) "
            "VALUES(?, ?, ?, 1, ?, ?)",
            (flow_id, name, json.dumps(doc), now, now),
        )
        self._conn.commit()
        return FlowRecord(flow_id, name, doc, 1, now, now)

    def get_flow(self, flow_id: str) -> FlowRecord:
        row = self._conn.execute("SELECT * FROM flows WHERE id = ?", (flow_id,)).fetchone()
        if row is None:
            raise ProjectStoreError(f"No flow with id {flow_id!r}")
        return _flow_from_row(row)

    def list_flows(self) -> list[FlowRecord]:
        rows = self._conn.execute("SELECT * FROM flows ORDER BY created_at").fetchall()
        return [_flow_from_row(r) for r in rows]

    # -- dashboards ----------------------------------------------------------------
    # 2026-07-14 (P5): saved by id, so re-saving an open dashboard updates it in place instead of
    # littering the project with copies (the flows table's insert-only behaviour is a known wart).

    def save_dashboard(
        self, name: str, layout: dict[str, Any], dashboard_id: str | None = None
    ) -> DashboardRecord:
        now = _now()
        did = dashboard_id or uuid.uuid4().hex
        row = self._conn.execute(
            "SELECT created_at FROM dashboards WHERE id = ?", (did,)
        ).fetchone()
        created = str(row["created_at"]) if row else now
        self._conn.execute(
            "INSERT INTO dashboards(id, name, layout_json, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "name = excluded.name, layout_json = excluded.layout_json, "
            "updated_at = excluded.updated_at",
            (did, name, json.dumps(layout), created, now),
        )
        self._conn.commit()
        return DashboardRecord(did, name, layout, created, now)

    def list_dashboards(self) -> list[DashboardRecord]:
        rows = self._conn.execute("SELECT * FROM dashboards ORDER BY created_at").fetchall()
        return [
            DashboardRecord(
                id=str(r["id"]),
                name=str(r["name"]),
                layout=json.loads(r["layout_json"]),
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]

    def delete_dashboard(self, dashboard_id: str) -> None:
        self._conn.execute("DELETE FROM dashboards WHERE id = ?", (dashboard_id,))
        self._conn.commit()

    # -- connections ---------------------------------------------------------------
    # 2026-07-31 (P7): upsert-by-id (the save_dashboard pattern) — re-saving an open API source or
    # playground request updates it in place instead of littering the project with copies. P7 rows
    # (playground requests, field mappings, REST destinations) live HERE, discriminated by
    # connector_type, because ProjectStore.open() has no migration path: a new table would force
    # SCHEMA_VERSION = 2 and make every touched project unopenable by older builds. Old builds
    # open the file and simply ignore connector types they don't know.

    def save_connection(
        self,
        name: str,
        connector_type: str,
        config: dict[str, Any] | None = None,
        secret_ref: str | None = None,
        connection_id: str | None = None,
    ) -> ConnectionRecord:
        now = _now()
        conn_id = connection_id or uuid.uuid4().hex
        row = self._conn.execute(
            "SELECT created_at FROM connections WHERE id = ?", (conn_id,)
        ).fetchone()
        created = str(row["created_at"]) if row else now
        self._conn.execute(
            "INSERT INTO connections(id, name, connector_type, config_json, secret_ref, "
            "created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "name = excluded.name, connector_type = excluded.connector_type, "
            "config_json = excluded.config_json, secret_ref = excluded.secret_ref, "
            "updated_at = excluded.updated_at",
            (conn_id, name, connector_type, json.dumps(config or {}), secret_ref, created, now),
        )
        self._conn.commit()
        return ConnectionRecord(
            conn_id, name, connector_type, config or {}, secret_ref, created, now
        )

    def get_connection(self, connection_id: str) -> ConnectionRecord:
        row = self._conn.execute(
            "SELECT * FROM connections WHERE id = ?", (connection_id,)
        ).fetchone()
        if row is None:
            raise ProjectStoreError(f"No connection with id {connection_id!r}")
        return _connection_from_row(row)

    def delete_connection(self, connection_id: str) -> None:
        self._conn.execute("DELETE FROM connections WHERE id = ?", (connection_id,))
        self._conn.commit()

    def list_connections(self) -> list[ConnectionRecord]:
        rows = self._conn.execute("SELECT * FROM connections ORDER BY created_at").fetchall()
        return [_connection_from_row(r) for r in rows]


def _connection_from_row(row: sqlite3.Row) -> ConnectionRecord:
    return ConnectionRecord(
        id=str(row["id"]),
        name=str(row["name"]),
        connector_type=str(row["connector_type"]),
        config=json.loads(row["config_json"]),
        secret_ref=row["secret_ref"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _flow_from_row(row: sqlite3.Row) -> FlowRecord:
    return FlowRecord(
        id=str(row["id"]),
        name=str(row["name"]),
        doc=json.loads(row["doc_json"]),
        version=int(row["version"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
