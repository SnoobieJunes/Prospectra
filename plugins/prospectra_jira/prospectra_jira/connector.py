# 2026-07-14 (P6): Jira — the reference implementation of the Prospectra plugin API.
#
# The whole connector is ~60 lines because it does not reinvent anything: it *builds a RestMapping*
# and lets Prospectra's REST tier do the auth, the pagination, and the flattening. That is the point
# of the reference — a SaaS connector should be a description of an API, not a re-implementation of
# HTTP.
#
# Jira Cloud specifics encoded here:
#   * auth is HTTP Basic with the *email* as the user and an API token as the password (Atlassian's
#     scheme; a bearer token is for OAuth apps, not personal tokens).
#   * /rest/api/3/search paginates by startAt/maxResults — the "offset" style.
#   * issues live under `issues`, and the fields worth having are nested one level down.
#
# Status: experimental. No live Jira has been called from this build (no credentials), and per
# Prospectra's honesty rule that badge does not change until one has been.

from __future__ import annotations

from typing import Any, ClassVar

import duckdb

from prospectra.core.connectors.base import Connector, ConnectorError, DatasetRef
from prospectra.core.connectors.rest import (
    Auth,
    Column,
    Pagination,
    RestConnector,
    RestMapping,
)

# The default view of an issue. A user can edit these away, or add their own custom fields, by
# editing the mapping this plugin produces — it is an ordinary RestMapping.
DEFAULT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("key", "key"),
    ("summary", "fields.summary"),
    ("status", "fields.status.name"),
    ("priority", "fields.priority.name"),
    ("issue_type", "fields.issuetype.name"),
    ("assignee", "fields.assignee.displayName"),
    ("reporter", "fields.reporter.displayName"),
    ("created", "fields.created"),
    ("resolved", "fields.resolutiondate"),
    ("story_points", "fields.customfield_10016"),
)


def _requested_fields() -> str:
    """Ask Jira only for the fields the columns actually read — a Jira issue is a huge document,
    and fetching all of it for ten columns is rude to someone else's server."""
    names = {path.split(".")[1] for _name, path in DEFAULT_COLUMNS if path.startswith("fields.")}
    return ",".join(sorted(names))


def jira_mapping(
    site: str,
    email: str,
    jql: str = "ORDER BY created DESC",
    secret_ref: str = "jira",
    name: str = "jira_issues",
) -> RestMapping:
    """Build the mapping that reads a Jira site's issues. `site` is e.g. acme.atlassian.net."""
    host = site.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    if not host:
        raise ConnectorError("Jira needs a site, e.g. acme.atlassian.net")
    return RestMapping(
        name=name,
        url=f"https://{host}/rest/api/3/search",
        params={"jql": jql, "fields": _requested_fields()},
        auth=Auth(kind="basic", user=email, secret_ref=secret_ref),
        pagination=Pagination(
            kind="offset",
            offset_param="startAt",
            size_param="maxResults",
            page_size=100,
            total_path="total",
        ),
        records_path="issues",
        columns=[Column(name=n, path=p) for n, p in DEFAULT_COLUMNS],
    )


class JiraConnector(Connector):
    """Jira Cloud issues, as a table."""

    type_name = "jira"
    display_name = "Jira (issues)"
    status: ClassVar = "experimental"  # no live Jira has been called from this build

    def __init__(
        self,
        site: str,
        email: str,
        api_token: str = "",
        jql: str = "ORDER BY created DESC",
        *,
        transport: Any = None,  # injected by tests
    ) -> None:
        self.mapping = jira_mapping(site, email, jql)
        self._rest = RestConnector(self.mapping, api_token or None, transport=transport)

    def list_datasets(self) -> list[DatasetRef]:
        return self._rest.list_datasets()

    def install(self, cursor: duckdb.DuckDBPyConnection, ref: DatasetRef, view_name: str) -> None:
        self._rest.install(cursor, ref, view_name)
