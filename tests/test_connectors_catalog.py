# 2026-07-13 (P1): Connector + catalog coverage — every verified path (CSV/TSV/JSON/Parquet,
# Excel sheets, SQLite via the generic SQLAlchemy connector) is exercised end-to-end into DuckDB.

import json

import pytest

from prospectra.core.catalog import Catalog
from prospectra.core.connectors import UnsupportedFileError
from prospectra.core.connectors.base import ConnectorError
from prospectra.core.connectors.sql_alchemy import SQLAlchemyConnector


@pytest.fixture()
def catalog():
    cat = Catalog()
    yield cat
    cat.close()


def _query(catalog, sql):
    return catalog.cursor().execute(sql).fetchall()


def test_open_csv(catalog, tmp_path):
    f = tmp_path / "orders.csv"
    f.write_text("region,sales\nWest,10\nEast,20\nWest,5\n", encoding="utf-8")
    (ds,) = catalog.open_file(f)
    assert ds.name == "orders"
    assert catalog.count_rows(ds.id) == 3
    assert catalog.describe(ds.id)[0][0] == "region"
    total = _query(catalog, f"SELECT sum(sales) FROM {ds.view_name}")[0][0]
    assert total == 35


def test_open_tsv_and_json(catalog, tmp_path):
    t = tmp_path / "t.tsv"
    t.write_text("a\tb\n1\t2\n", encoding="utf-8")
    j = tmp_path / "j.json"
    j.write_text(json.dumps([{"x": 1}, {"x": 5}]), encoding="utf-8")
    (ds_t,) = catalog.open_file(t)
    (ds_j,) = catalog.open_file(j)
    assert catalog.count_rows(ds_t.id) == 1
    assert _query(catalog, f"SELECT sum(x) FROM {ds_j.view_name}")[0][0] == 6


def test_open_parquet(catalog, tmp_path):
    p = tmp_path / "p.parquet"
    cur = catalog.cursor()
    cur.execute(f"COPY (SELECT range AS n FROM range(100)) TO '{p.as_posix()}' (FORMAT PARQUET)")
    (ds,) = catalog.open_file(p)
    assert catalog.count_rows(ds.id) == 100


def test_open_excel_sheets(catalog, tmp_path):
    pd = pytest.importorskip("pandas")
    f = tmp_path / "book.xlsx"
    with pd.ExcelWriter(f) as writer:  # openpyxl (dev dep) writes; calamine reads
        pd.DataFrame({"a": [1, 2]}).to_excel(writer, sheet_name="First", index=False)
        pd.DataFrame({"b": [3.5]}).to_excel(writer, sheet_name="Second", index=False)
    datasets = catalog.open_file(f)
    assert [d.name for d in datasets] == ["book · First", "book · Second"]
    assert catalog.count_rows(datasets[0].id) == 2
    assert _query(catalog, f"SELECT b FROM {datasets[1].view_name}")[0][0] == 3.5


def test_unsupported_suffix(catalog, tmp_path):
    f = tmp_path / "x.xyz"
    f.write_text("nope")
    with pytest.raises(UnsupportedFileError):
        catalog.open_file(f)


def test_missing_file(catalog, tmp_path):
    with pytest.raises(ConnectorError):
        catalog.open_file(tmp_path / "ghost.csv")


@pytest.fixture()
def sqlite_url(tmp_path):
    import sqlite3

    db = tmp_path / "sales.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE orders(id INTEGER, amount REAL)")
        conn.executemany("INSERT INTO orders VALUES(?, ?)", [(1, 9.5), (2, 0.5)])
        conn.execute("CREATE TABLE empty_t(x INTEGER)")
    return f"sqlite:///{db.as_posix()}"


def test_sqlalchemy_sqlite_roundtrip(catalog, sqlite_url):
    conn = catalog.add_connection("local sales", sqlite_url)
    assert conn.status == "verified"  # sqlite is the tested dialect
    assert catalog.list_tables(conn.id) == ["empty_t", "orders"]
    ds = catalog.open_table(conn.id, "orders")
    assert catalog.count_rows(ds.id) == 2
    assert _query(catalog, f"SELECT sum(amount) FROM {ds.view_name}")[0][0] == 10.0


def test_sqlalchemy_bad_url_fails_fast():
    with pytest.raises(ConnectorError):
        SQLAlchemyConnector("sqlite:///nonexistent/dir/x.db").test_connection()
