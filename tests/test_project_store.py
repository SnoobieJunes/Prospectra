# 2026-07-13 (P0): Project-file lifecycle — create/open/roundtrip/version guard. This is the
# durability layer every later phase writes through, so it gets covered first.

import pytest

from prospectra.core.project import (
    SCHEMA_VERSION,
    ProjectStore,
    ProjectStoreError,
    ProjectVersionError,
)


def test_create_and_reopen_roundtrip(tmp_path):
    path = tmp_path / "demo.prospectra"
    with ProjectStore.create(path) as store:
        assert store.schema_version == SCHEMA_VERSION
        store.set_meta("greeting", "hello")
        flow = store.save_flow("clean sales", {"nodes": [{"type": "input"}]})
        store.save_connection("local pg", "postgres", {"host": "db"}, secret_ref="kc:local-pg")

    with ProjectStore.open(path) as store:
        assert store.get_meta("greeting") == "hello"
        flows = store.list_flows()
        assert [f.name for f in flows] == ["clean sales"]
        assert store.get_flow(flow.id).doc == {"nodes": [{"type": "input"}]}
        (conn,) = store.list_connections()
        assert (conn.connector_type, conn.config, conn.secret_ref) == (
            "postgres",
            {"host": "db"},
            "kc:local-pg",
        )


def test_create_refuses_overwrite(tmp_path):
    path = tmp_path / "demo.prospectra"
    ProjectStore.create(path).close()
    with pytest.raises(ProjectStoreError):
        ProjectStore.create(path)


def test_open_missing_file(tmp_path):
    with pytest.raises(ProjectStoreError):
        ProjectStore.open(tmp_path / "nope.prospectra")


def test_open_non_project_file(tmp_path):
    junk = tmp_path / "junk.prospectra"
    junk.write_text("not a database")
    with pytest.raises(ProjectStoreError):
        ProjectStore.open(junk)


def test_open_newer_schema_refused(tmp_path):
    path = tmp_path / "future.prospectra"
    store = ProjectStore.create(path)
    store.set_meta("schema_version", str(SCHEMA_VERSION + 1))
    store.close()
    with pytest.raises(ProjectVersionError):
        ProjectStore.open(path)


def test_missing_flow_raises(tmp_path):
    with ProjectStore.create(tmp_path / "x.prospectra") as store, pytest.raises(ProjectStoreError):
        store.get_flow("does-not-exist")
