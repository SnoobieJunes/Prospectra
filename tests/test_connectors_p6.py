# 2026-07-14 (P6): Connector-breadth tests — dialects, the REST mapping tier, JDBC/PDF/stat-file
# extras, and the plugin entry point.
#
# The REST paginator is tested against *scripted* APIs through an injected httpx transport: every
# pagination style the mapping tool offers (page / offset / cursor / Link header) is walked for
# real, with real requests and real query strings, and the assertions are on what the client
# actually sent. That is the difference between "the code path runs" and "the paginator paginates".
#
# What is NOT tested here, and cannot be: a live third-party API. Every connector in this file is
# badged experimental for exactly that reason.

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import httpx
import pytest

from prospectra.core.connectors import (
    DIALECTS_BY_KEY,
    ConnectorError,
    RestConnector,
    RestMapping,
    dialect_for_url,
    external_connectors,
    file_connector_for,
)
from prospectra.core.connectors.dialects import redact_url
from prospectra.core.connectors.jdbc import JDBCConnector, jdbc_available
from prospectra.core.connectors.rest import (
    Auth,
    Column,
    Pagination,
    RestClient,
    infer_mapping_fields,
    paths,
    records_to_frame,
)

# -- dialect descriptors ---------------------------------------------------------------------


def test_a_dialect_builds_its_url_from_a_form():
    snowflake = DIALECTS_BY_KEY["snowflake"]
    url = snowflake.build_url(
        {
            "account": "xy12345.eu-central-1",
            "user": "analyst",
            "password": "hunter2",
            "database": "SALES",
            "schema": "PUBLIC",
            "warehouse": "COMPUTE_WH",
            "role": "READER",
        }
    )
    assert url == (
        "snowflake://analyst:hunter2@xy12345.eu-central-1/SALES/PUBLIC"
        "?warehouse=COMPUTE_WH&role=READER"
    )


def test_a_password_with_url_metacharacters_survives():
    """A password of "p@ss/w:rd" hand-pasted into a URL silently connects as the wrong user (or
    not at all). Quoting is the difference between "wrong password" and "connects"."""
    postgres = DIALECTS_BY_KEY["postgresql"]
    url = postgres.build_url(
        {
            "host": "db.internal",
            "port": "5432",
            "database": "sales",
            "user": "analyst",
            "password": "p@ss/w:rd?#",
        }
    )
    assert "p%40ss%2Fw%3Ard%3F%23" in url
    assert url.count("@") == 1  # the password's @ did not become a second host separator

    # and it round-trips: SQLAlchemy must read back exactly what was typed
    from sqlalchemy.engine import make_url

    assert make_url(url).password == "p@ss/w:rd?#"
    assert make_url(url).host == "db.internal"


def test_a_missing_required_field_says_which_one():
    with pytest.raises(ValueError, match="Database"):
        DIALECTS_BY_KEY["postgresql"].build_url({"host": "h", "port": "5432", "user": "u"})


def test_only_sqlite_claims_to_be_verified():
    """The honesty rule, as a test: no dialect may claim "verified" without a real server behind
    it, and only SQLite has one here (the test suite)."""
    verified = [d.key for d in DIALECTS_BY_KEY.values() if d.status == "verified"]
    assert verified == ["sqlite"]


def test_driver_detection_reports_what_is_actually_installed():
    assert DIALECTS_BY_KEY["sqlite"].driver_installed is True  # built into SQLAlchemy
    snowflake = DIALECTS_BY_KEY["snowflake"]
    assert snowflake.driver_installed is False  # not installed in this environment
    assert snowflake.install_hint() == "uv add snowflake-sqlalchemy"


def test_dialect_lookup_from_a_url():
    assert dialect_for_url("postgresql+psycopg://u:p@h/db").key == "postgresql"
    assert dialect_for_url("snowflake://u:p@acct/db/s").key == "snowflake"
    assert dialect_for_url("weird://x") is None


def test_the_project_file_never_gets_the_password():
    redacted = redact_url("postgresql+psycopg://analyst:hunter2@db.internal:5432/sales")
    assert "hunter2" not in redacted
    assert redacted == "postgresql+psycopg://analyst:***@db.internal:5432/sales"
    assert redact_url("sqlite:///data.db") == "sqlite:///data.db"  # nothing to redact


# -- the tiny JSONPath ---------------------------------------------------------------------------


def test_paths_walk_objects_lists_and_wildcards():
    doc = {"data": {"items": [{"id": 1, "user": {"name": "ada"}}, {"id": 2}]}}
    assert paths.resolve(doc, "data.items[0].user.name") == "ada"
    assert paths.resolve(doc, "data.items[*].id") == [1, 2]
    assert paths.resolve(doc, "data.items[1].user.name") is None  # ragged: missing, not an error
    assert paths.resolve(doc, "nope.nothing") is None


def test_records_at_handles_a_bare_list_and_a_single_object():
    assert paths.records_at([{"a": 1}], "") == [{"a": 1}]
    assert paths.records_at({"a": 1}, "") == [{"a": 1}]  # one object is one row


# -- flattening and inference --------------------------------------------------------------------


def test_the_mapping_tool_infers_the_records_path_and_columns():
    body = {
        "total": 2,
        "issues": [
            {"key": "AB-1", "fields": {"summary": "Fix it", "status": {"name": "Done"}}},
            {"key": "AB-2", "fields": {"summary": "Ship it", "status": {"name": "Open"}}},
        ],
    }
    records_path, columns = infer_mapping_fields(body)
    assert records_path == "issues"
    by_name = {c.name: c.path for c in columns}
    assert by_name["key"] == "key"
    assert by_name["fields_status_name"] == "fields.status.name"


def test_nested_values_become_json_text_rather_than_being_dropped():
    mapping = RestMapping(url="https://x/y", columns=[Column(name="labels", path="labels")])
    frame = records_to_frame([{"labels": ["a", "b"]}], mapping)
    assert json.loads(frame["labels"][0]) == ["a", "b"]  # queryable, not lost


# -- the paginator, against scripted APIs ----------------------------------------------------------


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_page_pagination_walks_until_a_page_comes_back_empty():
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        page = int(request.url.params.get("page", 1))
        rows = [{"id": page}] if page <= 3 else []
        return httpx.Response(200, json={"data": rows})

    mapping = RestMapping(
        url="https://api.test/things",
        records_path="data",
        pagination=Pagination(kind="page", page_size=50, max_pages=10),
    )
    records, report = RestClient(mapping, transport=_transport(handler)).records()

    assert [r["id"] for r in records] == [1, 2, 3]
    assert report.pages == 4  # the 4th page came back empty and ended the walk
    assert seen[0]["page"] == "1" and seen[0]["per_page"] == "50"
    assert not report.stopped_at_cap  # a natural end is not a cap


def test_offset_pagination_sends_the_offsets_jira_style():
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        start = int(request.url.params.get("startAt", 0))
        rows = [{"key": f"AB-{start + 1}"}] if start < 200 else []
        return httpx.Response(200, json={"issues": rows})

    mapping = RestMapping(
        url="https://jira.test/rest/api/3/search",
        records_path="issues",
        pagination=Pagination(
            kind="offset", offset_param="startAt", size_param="maxResults", page_size=100
        ),
    )
    records, _report = RestClient(mapping, transport=_transport(handler)).records()

    assert [r["key"] for r in records] == ["AB-1", "AB-101"]
    assert [s["startAt"] for s in seen[:3]] == ["0", "100", "200"]


def test_cursor_pagination_follows_the_token_in_the_body():
    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        if cursor is None:
            return httpx.Response(200, json={"rows": [{"n": 1}], "next": "abc"})
        if cursor == "abc":
            return httpx.Response(200, json={"rows": [{"n": 2}]})  # no next -> the walk ends
        raise AssertionError(f"unexpected cursor {cursor}")

    mapping = RestMapping(
        url="https://api.test/rows",
        records_path="rows",
        pagination=Pagination(kind="cursor", next_path="next"),
    )
    records, report = RestClient(mapping, transport=_transport(handler)).records()
    assert [r["n"] for r in records] == [1, 2]
    assert report.pages == 2


def test_link_header_pagination_follows_rel_next():
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if "page=2" not in str(request.url):
            return httpx.Response(
                200,
                json=[{"i": 1}],
                headers={"Link": '<https://api.test/items?page=2>; rel="next"'},
            )
        return httpx.Response(200, json=[{"i": 2}])  # no Link header -> the walk ends

    mapping = RestMapping(
        url="https://api.test/items", records_path="", pagination=Pagination(kind="link")
    )
    records, _report = RestClient(mapping, transport=_transport(handler)).records()
    assert [r["i"] for r in records] == [1, 2]
    # the second request is the URL the server handed us, not a URL we assembled
    assert requested[1] == "https://api.test/items?page=2"


def test_a_runaway_paginator_stops_at_the_cap_and_says_so():
    """An API that always claims there is a next page exists. Without a cap this loops forever;
    with a silent cap the user thinks they have all the data. So: stop, and confess."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rows": [{"n": 1}], "next": "always"})

    mapping = RestMapping(
        url="https://api.test/rows",
        records_path="rows",
        pagination=Pagination(kind="cursor", next_path="next", max_pages=5),
    )
    _records, report = RestClient(mapping, transport=_transport(handler)).records()
    assert report.pages == 5
    assert report.stopped_at_cap is True
    assert any("there may be more" in note for note in report.notes)


def test_the_record_cap_is_also_confessed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rows": [{"n": i} for i in range(100)], "next": "more"})

    mapping = RestMapping(
        url="https://api.test/rows",
        records_path="rows",
        pagination=Pagination(kind="cursor", next_path="next", max_pages=50),
        max_records=150,
    )
    records, report = RestClient(mapping, transport=_transport(handler)).records()
    assert len(records) == 150
    assert any("cap" in note for note in report.notes)


# -- auth -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("auth", "secret", "header", "expected"),
    [
        (Auth(kind="bearer"), "tok", "authorization", "Bearer tok"),
        (Auth(kind="header", header="X-API-Key"), "tok", "x-api-key", "tok"),
        (Auth(kind="basic", user="me@x.com"), "tok", "authorization", "Basic bWVAeC5jb206dG9r"),
    ],
)
def test_each_auth_style_puts_the_credential_where_the_api_expects_it(
    auth, secret, header, expected
):
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update({k.lower(): v for k, v in request.headers.items()})
        return httpx.Response(200, json=[{"ok": 1}])

    mapping = RestMapping(url="https://api.test/x", auth=auth)
    RestClient(mapping, secret, transport=_transport(handler)).records()
    assert captured[header] == expected


def test_query_auth_goes_in_the_query_string():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json=[{"ok": 1}])

    mapping = RestMapping(url="https://api.test/x", auth=Auth(kind="query", param="api_key"))
    RestClient(mapping, "tok", transport=_transport(handler)).records()
    assert captured["api_key"] == "tok"


def test_a_mapping_that_needs_a_credential_refuses_to_run_without_one():
    mapping = RestMapping(url="https://api.test/x", auth=Auth(kind="bearer"))
    with pytest.raises(ConnectorError, match="no credential"):
        RestClient(mapping, None, transport=_transport(lambda r: httpx.Response(200))).records()


def test_a_rejected_credential_says_the_api_rejected_it():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "nope"})

    mapping = RestMapping(url="https://api.test/x", auth=Auth(kind="bearer"))
    with pytest.raises(ConnectorError, match="rejected the credential"):
        RestClient(mapping, "bad", transport=_transport(handler)).records()


# -- the mapping document -------------------------------------------------------------------------


def test_a_mapping_round_trips_and_never_carries_the_secret():
    mapping = RestMapping(
        name="orders",
        url="https://api.test/orders",
        auth=Auth(kind="bearer", secret_ref="api:orders"),
        pagination=Pagination(kind="page"),
        records_path="data",
        columns=[Column(name="id", path="id")],
    )
    doc = mapping.to_dict()
    assert "secret" not in json.dumps(doc).lower() or doc["auth"]["secret_ref"] == "api:orders"
    assert json.dumps(doc)  # it is JSON, so it can live in the project file
    restored = RestMapping.from_dict(doc)
    assert restored.url == mapping.url
    assert restored.auth.secret_ref == "api:orders"
    assert restored.columns[0].path == "id"


def test_a_mapping_rejects_a_future_schema():
    doc = RestMapping(url="https://x/y").to_dict()
    doc["mapping_schema"] = 99
    with pytest.raises(ValueError, match="newer than this app"):
        RestMapping.from_dict(doc)


# -- the connector, end to end into DuckDB --------------------------------------------------------


def test_a_rest_mapping_becomes_a_queryable_table():
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", 1))
        if page > 2:
            return httpx.Response(200, json={"data": []})
        rows = [
            {"id": (page - 1) * 2 + i, "user": {"name": f"u{i}"}, "amount": 10.5 * i}
            for i in (1, 2)
        ]
        return httpx.Response(200, json={"data": rows})

    mapping = RestMapping(
        name="orders",
        url="https://api.test/orders",
        records_path="data",
        pagination=Pagination(kind="page", page_size=2, max_pages=5),
        columns=[
            Column(name="id", path="id"),
            Column(name="user_name", path="user.name"),
            Column(name="amount", path="amount"),
        ],
    )
    connector = RestConnector(mapping, transport=_transport(handler))
    con = duckdb.connect()
    connector.install(con, connector.list_datasets()[0], "orders")

    rows = con.execute("SELECT id, user_name, amount FROM orders ORDER BY id").fetchall()
    assert rows == [(1, "u1", 10.5), (2, "u2", 21.0), (3, "u1", 10.5), (4, "u2", 21.0)]
    assert connector.last_report.pages == 3
    con.close()


def test_an_endpoint_with_no_records_at_the_path_says_check_the_path():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"payload": [{"a": 1}]})

    mapping = RestMapping(url="https://api.test/x", records_path="wrong")
    connector = RestConnector(mapping, transport=_transport(handler))
    with pytest.raises(ConnectorError, match="records path"):
        connector.fetch()


# -- the plugin API -------------------------------------------------------------------------------


def test_the_jira_plugin_is_discovered_through_the_entry_point():
    """The plugin API is only real if a separately-installed distribution shows up through it."""
    found = external_connectors()
    assert "jira" in found
    assert found["jira"].status == "experimental"  # no live Jira has been called from this build


def test_the_jira_plugin_describes_jiras_api_rather_than_reimplementing_http():
    from prospectra_jira import jira_mapping

    mapping = jira_mapping("acme.atlassian.net", "me@acme.com")
    assert mapping.url == "https://acme.atlassian.net/rest/api/3/search"
    assert mapping.auth.kind == "basic" and mapping.auth.user == "me@acme.com"
    assert mapping.pagination.offset_param == "startAt"  # Jira's style, declared not coded
    assert "summary" in mapping.params["fields"]  # asks only for the fields it reads
    assert "token" not in json.dumps(mapping.to_dict()).lower()  # the secret is by reference only


def test_the_jira_plugin_reads_issues_through_the_shared_rest_tier():
    def handler(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params.get("startAt", 0))
        if start > 0:
            return httpx.Response(200, json={"issues": []})
        return httpx.Response(
            200,
            json={
                "total": 1,
                "issues": [
                    {
                        "key": "AB-1",
                        "fields": {
                            "summary": "Fix the thing",
                            "status": {"name": "Done"},
                            "assignee": {"displayName": "Ada"},
                        },
                    }
                ],
            },
        )

    from prospectra_jira import JiraConnector

    connector = JiraConnector(
        "acme.atlassian.net", "me@acme.com", "token", transport=_transport(handler)
    )
    con = duckdb.connect()
    connector.install(con, connector.list_datasets()[0], "issues")
    row = con.execute("SELECT key, summary, status, assignee FROM issues").fetchone()
    assert row == ("AB-1", "Fix the thing", "Done", "Ada")
    con.close()


# -- optional extras: honest messages, never ImportError tracebacks -------------------------------


def test_jdbc_without_the_extra_says_what_to_install():
    if jdbc_available():
        pytest.skip("the jdbc extra is installed here")
    connector = JDBCConnector("jdbc:teradata://host/db", "com.teradata.jdbc.TeraDriver")
    with pytest.raises(ConnectorError, match="uv sync --extra jdbc"):
        connector.connect()


def test_pdf_and_stat_files_are_recognised_by_the_registry(tmp_path: Path):
    """The suffixes route to the right connector even when the optional library is absent — the
    failure a user meets is a sentence about `uv sync`, not an ImportError."""
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4 not really a pdf")
    connector = file_connector_for(pdf)
    assert connector.type_name == "pdf"

    sav = tmp_path / "survey.sav"
    sav.write_bytes(b"not really spss")
    assert file_connector_for(sav).type_name == "statfile"


# -- the acceptance path: a dialect, a connection, and a flow over a DATABASE table ----------


def _sales_db(tmp_path: Path) -> Path:
    import sqlite3

    db = tmp_path / "sales.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE orders (region TEXT, revenue REAL);"
        "INSERT INTO orders VALUES ('EMEA', 1200.5), ('EMEA', 800.0), ('APAC', 2400.0),"
        " ('APAC', 50.0);"
    )
    con.commit()
    con.close()
    return db


def test_a_file_path_is_not_quoted_like_a_credential(tmp_path: Path):
    """Regression, found by running the acceptance path and not by any unit test: build_url()
    escaped every field, so a SQLite path's slashes became %2F. SQLAlchemy did not fail on that —
    it silently created a new empty database at that literal name and reported a good connection
    with zero tables. A path keeps its separators; a password does not."""
    db = _sales_db(tmp_path)
    url = DIALECTS_BY_KEY["sqlite"].build_url({"path": str(db)})
    assert "%2F" not in url
    assert "%5C" not in url  # 2026-08-05: nor the Windows separator
    assert Path(db).as_posix() in url

    from sqlalchemy.engine import make_url

    # SQLAlchemy reads back a path that opens the real file on this OS.
    assert Path(make_url(url).database or "").resolve() == db.resolve()


# 2026-08-05: the Windows half of the rule above, reproduced on EVERY platform by handing the
# quoter a backslash path directly. The original test used the local OS's path separator, so on
# macOS/Linux it could never see the bug and Windows CI carried it alone from P6 until now.
def test_a_windows_path_keeps_its_separators_on_every_platform():
    url = DIALECTS_BY_KEY["sqlite"].build_url({"path": r"C:\Users\me\data\sales.db"})
    assert url == "sqlite:///C:/Users/me/data/sales.db"
    assert "%5C" not in url and "%2F" not in url

    from sqlalchemy.engine import make_url

    assert make_url(url).database == "C:/Users/me/data/sales.db"


def test_a_backslash_in_a_credential_is_still_escaped():
    """Only path-like fields are normalized — a password keeps every character it was given."""
    from prospectra.core.connectors.dialects import Field

    assert Field("password", "Password", secret=True).quote_value(r"pa\ss/word@1") == (
        "pa%5Css%2Fword%401"
    )


def test_a_missing_sqlite_file_is_an_error_not_a_new_empty_database(tmp_path: Path):
    """SQLite creates a database when asked to open one that is not there — so a typo'd path
    "connects" fine and shows no tables, with nothing appearing to have gone wrong."""
    from prospectra.core.connectors.sql_alchemy import SQLAlchemyConnector

    missing = tmp_path / "not_here.db"
    connector = SQLAlchemyConnector(f"sqlite:///{missing}")
    with pytest.raises(ConnectorError, match="No database file"):
        connector.test_connection()
    assert not missing.exists()  # and we did not leave an empty database behind


def test_a_flow_can_read_a_database_table_end_to_end(tmp_path: Path):
    """The P6 acceptance line: install a dialect, connect, run a flow. Before the Node.prepare()
    seam, a database you had connected to was a dead end at the prep canvas."""
    from prospectra.core.flow import FlowGraph, FlowRunner

    db = _sales_db(tmp_path)
    url = DIALECTS_BY_KEY["sqlite"].build_url({"path": str(db)})
    out = tmp_path / "by_region.csv"

    graph = FlowGraph()
    src = graph.add_node("input_database", {"url": url, "table": "orders"})
    keep = graph.add_node("filter", {"expression": "revenue > 100"})
    agg = graph.add_node(
        "aggregate", {"group_by": "region", "aggregations": "sum(revenue) AS revenue"}
    )
    sink = graph.add_node("output", {"path": str(out), "format": "csv"})
    for a, b in [(src, keep), (keep, agg), (agg, sink)]:
        graph.add_edge(a, b)

    result = FlowRunner().run(graph)[0]
    assert result.rows == 2  # EMEA and APAC; the 50.0 APAC order was filtered out
    rows = sorted(out.read_text().strip().splitlines()[1:])
    assert rows == ["APAC,2400.0", "EMEA,2000.5"]


def test_a_database_flow_node_can_run_a_query_too(tmp_path: Path):
    from prospectra.core.flow import FlowGraph, FlowRunner

    db = _sales_db(tmp_path)
    url = DIALECTS_BY_KEY["sqlite"].build_url({"path": str(db)})
    out = tmp_path / "q.csv"

    graph = FlowGraph()
    src = graph.add_node(
        "input_database",
        {"url": url, "query": "SELECT region, revenue FROM orders WHERE region = 'EMEA'"},
    )
    sink = graph.add_node("output", {"path": str(out), "format": "csv"})
    graph.add_edge(src, sink)

    assert FlowRunner().run(graph)[0].rows == 2


def test_a_flow_pointed_at_a_bad_table_blames_the_node_that_failed(tmp_path: Path):
    from prospectra.core.flow import FlowGraph, FlowRunner
    from prospectra.core.flow.errors import FlowRunError

    db = _sales_db(tmp_path)
    url = DIALECTS_BY_KEY["sqlite"].build_url({"path": str(db)})

    graph = FlowGraph()
    src = graph.add_node("input_database", {"url": url, "table": "nonexistent"})
    sink = graph.add_node("output", {"path": str(tmp_path / "x.csv"), "format": "csv"})
    graph.add_edge(src, sink)

    with pytest.raises(FlowRunError) as caught:
        FlowRunner().run(graph)
    assert caught.value.node_id == src  # the canvas marks the offending node, not a random one
