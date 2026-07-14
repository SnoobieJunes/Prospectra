# Writing a connector

A Prospectra connector is **two methods and an entry point**. Nothing in Prospectra needs to change
to accept yours — install your package and it appears in the app.

This page walks the real thing: `plugins/prospectra_jira/` in this repo is the reference
implementation, and it is under 100 lines.

## The contract

```python
class Connector(ABC):
    type_name: ClassVar[str]        # "jira"
    display_name: ClassVar[str]     # "Jira (issues)"
    status: ClassVar[str]           # "verified" | "experimental"  — see Honesty, below

    def list_datasets(self) -> list[DatasetRef]:
        """What can be opened from this source (files, sheets, tables)."""

    def install(self, cursor, ref: DatasetRef, view_name: str) -> None:
        """Make `ref` queryable in the DuckDB session under `view_name`."""
```

`install` creates either a **VIEW** (cheap, re-read per query — right for local files) or a
**TABLE** (materialized — required for anything that came over a network, so a chart redraw does
not re-hit someone's API).

## The whole plugin

`my_connector/pyproject.toml`:

```toml
[project]
name = "prospectra-widgets"
version = "0.1.0"
dependencies = ["prospectra"]

# This line is the entire registration mechanism.
[project.entry-points."prospectra.connectors"]
widgets = "prospectra_widgets.connector:WidgetConnector"
```

`my_connector/prospectra_widgets/connector.py`:

```python
from typing import ClassVar
import duckdb, pandas as pd
from prospectra.core.connectors.base import Connector, ConnectorError, DatasetRef


class WidgetConnector(Connector):
    type_name = "widgets"
    display_name = "Widget API"
    status: ClassVar = "experimental"      # until you have run it against the real thing

    def __init__(self, api_token: str = "") -> None:
        self._token = api_token

    def list_datasets(self) -> list[DatasetRef]:
        return [DatasetRef(name="widgets", kind="table")]

    def install(self, cursor: duckdb.DuckDBPyConnection, ref: DatasetRef, view_name: str) -> None:
        frame = pd.DataFrame(fetch_widgets(self._token))   # your code
        cursor.register("_tmp", frame)
        try:
            cursor.execute(f"CREATE OR REPLACE TABLE {view_name} AS SELECT * FROM _tmp")
        finally:
            cursor.unregister("_tmp")
```

```sh
uv add ./my_connector      # done — it shows up in `prospectra connectors` and in the app
```

## Don't reimplement HTTP — describe the API

If your source is a JSON REST API, you almost certainly should not write the HTTP code at all.
Build a `RestMapping` and let Prospectra's REST tier do auth, pagination, and flattening. That is
what the Jira plugin does, and it is why it is 60 lines instead of 300:

```python
from prospectra.core.connectors.rest import Auth, Column, Pagination, RestConnector, RestMapping

mapping = RestMapping(
    name="jira_issues",
    url="https://acme.atlassian.net/rest/api/3/search",
    auth=Auth(kind="basic", user="me@acme.com", secret_ref="jira"),   # NOT the token itself
    pagination=Pagination(kind="offset", offset_param="startAt", size_param="maxResults"),
    records_path="issues",
    columns=[Column(name="key", path="key"), Column(name="summary", path="fields.summary")],
)
```

Pagination styles supported out of the box: `page`, `offset`, `cursor`, `link` (RFC 5988).
Auth styles: `bearer`, `basic`, `header`, `query`.

## Rules your connector must follow

**Secrets go in the OS keychain, never in the project file.** A mapping or connection record stores
a `secret_ref` — the *name* of a keychain entry. A `.prospectra` file gets emailed and committed;
a password inside one is a leak with a long tail.

**Status tells the truth.** `status = "experimental"` means "implemented, but nobody has watched it
work against the real thing." You may only set `"verified"` after a real call against a real server
has been made and observed. This is not paperwork — the badge is shown to users, and a badge that
lies is worse than no badge.

**Build SQL through `prospectra.core.sqlutil`.** `ident()` and `path_lit()` handle quoting and
Windows paths (a raw `str(Path)` with backslashes in a SQL literal breaks on the testers' machines).

**Never import Qt.** Connectors live in `prospectra.core`, which is the headless engine; an
import-linter contract enforces it. Your connector must work from the CLI with no display.

## Other extension points

Same mechanism, different group:

| Entry-point group | You implement | Registers a |
|---|---|---|
| `prospectra.connectors` | `Connector` | data source |
| `prospectra.flow_nodes` | `Node` | prep-flow node |
| `prospectra.analyses` | analysis | mining step |
| `prospectra.llm_providers` | `Provider` | LLM backend |
| `prospectra.chart_types` | chart | dashboard chart |

## A caveat about packaged builds

The **packaged** app (the PyInstaller bundle) can only carry plugins that were installed when it
was built — there is no `pip` inside a frozen app. To use your own connector, run Prospectra from
source (`uv sync && uv run prospectra`). This is a real limitation, not an oversight; it is
recorded in `Deviations.md`.
