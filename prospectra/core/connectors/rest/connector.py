# 2026-07-14 (P6): The REST connector — a saved mapping, installed as a DuckDB table.
#
# It is a materialized TABLE, never a view: the rows came over the network, so re-reading them per
# query would re-hit someone's API. Refreshing is an explicit act.
#
# Status is "experimental" and stays that way. The paginator, the auth builders, and the flattener
# are all tested against scripted APIs — but no live third-party API has been called from this
# build, so per CLAUDE.md the badge tells the truth rather than the intent.

from __future__ import annotations

import logging
from typing import Any, ClassVar

import duckdb

from prospectra.core.connectors.base import Connector, ConnectorError, DatasetRef
from prospectra.core.connectors.rest.client import FetchReport, RestClient
from prospectra.core.connectors.rest.flatten import records_to_frame
from prospectra.core.connectors.rest.mapping import RestMapping

logger = logging.getLogger(__name__)


class RestConnector(Connector):
    """Any JSON REST/OData endpoint, described by a saved mapping."""

    type_name = "rest"
    display_name = "REST / OData API (mapping)"
    status: ClassVar = "experimental"  # no live third-party API has been called from this build

    def __init__(
        self,
        mapping: RestMapping,
        secret: str | None = None,
        *,
        transport: Any = None,  # injected by tests; None -> the real network
    ) -> None:
        mapping.validate()
        self.mapping = mapping
        self._secret = secret
        self._transport = transport
        self.last_report: FetchReport | None = None

    def _client(self) -> RestClient:
        return RestClient(self.mapping, self._secret, transport=self._transport)

    def list_datasets(self) -> list[DatasetRef]:
        return [DatasetRef(name=self.mapping.name, kind="table")]

    def sample(self) -> Any:
        """One page, unpaginated — what the mapping tool infers columns from."""
        client = self._client()
        try:
            return client._get(self.mapping.url, {**self.mapping.params, **client._auth_params()})
        finally:
            client.close()

    def fetch(self) -> tuple[Any, FetchReport]:
        client = self._client()
        try:
            records, report = client.records()
        finally:
            client.close()
        self.last_report = report
        frame = records_to_frame(records, self.mapping)
        if frame.empty:
            raise ConnectorError(
                f"{self.mapping.url} returned no records at path "
                f"{self.mapping.records_path or '(root)'!r}. Check the mapping's records path."
            )
        return frame, report

    def install(self, cursor: duckdb.DuckDBPyConnection, ref: DatasetRef, view_name: str) -> None:
        frame, report = self.fetch()
        cursor.register("_prospectra_tmp_rest", frame)
        try:
            # A TABLE, not a VIEW: these rows came off the network and must not be re-fetched on
            # every query.
            cursor.execute(
                f"CREATE OR REPLACE TABLE {view_name} AS SELECT * FROM _prospectra_tmp_rest"
            )
        finally:
            cursor.unregister("_prospectra_tmp_rest")
        logger.info(
            "REST mapping %s: %d record(s) over %d page(s)%s",
            self.mapping.name,
            report.records,
            report.pages,
            " (hit a cap)" if report.stopped_at_cap else "",
        )
