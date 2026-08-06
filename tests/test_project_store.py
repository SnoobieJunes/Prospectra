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


# 2026-07-31 (P7): connections gained upsert-by-id (the save_dashboard pattern). Before this,
# every save was an insert — which is why re-saving an API source littered the project with copies.


def test_same_id_save_connection_updates_rather_than_duplicating(tmp_path):
    with ProjectStore.create(tmp_path / "p.prospectra") as store:
        first = store.save_connection("orders api", "rest", {"url": "https://a"})
        updated = store.save_connection(
            "orders api v2", "rest", {"url": "https://b"}, connection_id=first.id
        )
        assert updated.id == first.id
        assert updated.created_at == first.created_at  # an update, not a re-creation

        records = store.list_connections()
        assert len(records) == 1
        assert records[0].name == "orders api v2"
        assert records[0].config == {"url": "https://b"}


def test_get_and_delete_connection(tmp_path):
    with ProjectStore.create(tmp_path / "p.prospectra") as store:
        record = store.save_connection("x", "http_request", {"url": "https://x"})
        assert store.get_connection(record.id).name == "x"
        store.delete_connection(record.id)
        assert store.list_connections() == []
        with pytest.raises(ProjectStoreError):
            store.get_connection(record.id)


def test_a_rest_mapping_round_trips_through_the_connections_table(tmp_path):
    from prospectra.core.connectors.rest import RestMapping

    mapping = RestMapping(
        name="products",
        url="https://api.test/products",
        headers={"X-Tenant": "acme"},
        records_path="data",
        rate_limit_per_sec=2.0,
    )
    path = tmp_path / "p.prospectra"
    with ProjectStore.create(path) as store:
        store.save_connection(mapping.name, "rest", mapping.to_dict())
    with ProjectStore.open(path) as store:
        (record,) = store.list_connections()
        assert RestMapping.from_dict(record.config) == mapping
