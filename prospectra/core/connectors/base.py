# 2026-07-13 (P1): Connector contract. A connector enumerates datasets (files/sheets/tables) and
# installs one into the shared DuckDB session as a view or table.
# Why: one small ABC is the whole extension surface — third parties implement these two methods
# and register via the `prospectra.connectors` entry-point group. Status is part of the contract:
# per CLAUDE.md honesty rules, connectors never tested against a real backend stay "experimental".

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

import duckdb

ConnectorStatus = Literal["verified", "experimental"]


class ConnectorError(Exception):
    """Raised when a source cannot be listed or installed."""


@dataclass(frozen=True)
class DatasetRef:
    """One openable dataset within a source (a file, a sheet, a table)."""

    name: str
    kind: Literal["file", "sheet", "table"]
    detail: dict[str, Any] = field(default_factory=dict)


class Connector(ABC):
    type_name: ClassVar[str]
    display_name: ClassVar[str]
    status: ClassVar[ConnectorStatus]

    @abstractmethod
    def list_datasets(self) -> list[DatasetRef]:
        """Enumerate datasets this source offers."""

    @abstractmethod
    def install(self, cursor: duckdb.DuckDBPyConnection, ref: DatasetRef, view_name: str) -> None:
        """Make `ref` queryable in the DuckDB session under `view_name`.

        Implementations must create a VIEW (cheap, re-read on query — right for local files)
        or a TABLE (materialized — required for in-memory sources such as DataFrames, so the
        result is visible to every cursor of the session).
        """
