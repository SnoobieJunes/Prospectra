# 2026-07-13 (P4): The sandbox is a security boundary, so it is tested like one — with the
# attacks. SQL written by a model is untrusted input: it must not be able to read a file, escape
# into another database, escalate its own permissions, or drag an unbounded result into the chat.

import json

import pytest

from prospectra.core.catalog import Catalog
from prospectra.core.llm import PrivacyLevel, ToolBox
from prospectra.core.llm.sandbox import QuerySandbox
from prospectra.core.llm.sqlguard import MAX_ROWS, UnsafeSQLError, check_select, wrap_with_limit
from prospectra.core.llm.tools import ToolError


@pytest.fixture()
def secret_file(tmp_path):
    path = tmp_path / "secret.csv"
    path.write_text("secret\nEXFILTRATED\n", encoding="utf-8")
    return path


@pytest.fixture()
def box(tmp_path):
    data = tmp_path / "sales.csv"
    data.write_text("region,amount\nWest,10\nEast,20\n", encoding="utf-8")
    catalog = Catalog()
    catalog.open_file(data)
    sandbox = QuerySandbox(catalog, list(catalog.datasets))
    yield ToolBox(sandbox, PrivacyLevel.SAMPLE_ROWS)
    sandbox.close()
    catalog.close()


# -- the SQL guard ----------------------------------------------------------------------------


def test_only_select_survives_the_guard():
    assert check_select("SELECT 1") == "SELECT 1"
    assert check_select("  WITH x AS (SELECT 1) SELECT * FROM x;  ").startswith("WITH")
    for hostile in (
        "DROP TABLE sales",
        "DELETE FROM sales",
        "UPDATE sales SET amount = 0",
        "CREATE TABLE evil (x INT)",
        "ATTACH 'other.db'",
        "COPY sales TO 'out.csv'",
        "SET enable_external_access=true",
        "INSTALL httpfs",
    ):
        with pytest.raises(UnsafeSQLError):
            check_select(hostile)


def test_statement_stacking_is_blocked():
    with pytest.raises(UnsafeSQLError, match="one statement"):
        check_select("SELECT 1; DROP TABLE sales")


def test_empty_and_unparseable_sql_are_refused():
    with pytest.raises(UnsafeSQLError):
        check_select("   ")
    with pytest.raises(UnsafeSQLError):
        check_select("SELEKT * FROM sales")


def test_results_are_row_capped():
    assert f"LIMIT {MAX_ROWS}" in wrap_with_limit("SELECT * FROM sales")


# -- the sandbox itself -------------------------------------------------------------------------


def test_the_sandbox_cannot_read_a_file(box, secret_file):
    """Even a legal SELECT must not reach the filesystem — this is why SELECT-only is not enough
    on its own and the model gets its own locked-down database."""
    for attack in (
        f"SELECT * FROM read_csv('{secret_file.as_posix()}')",
        f"SELECT * FROM '{secret_file.as_posix()}'",
        f"SELECT * FROM read_parquet('{secret_file.as_posix()}')",
    ):
        with pytest.raises(Exception) as excinfo:  # duckdb.PermissionException
            box.call("run_sql", {"sql": attack})
        assert "EXFILTRATED" not in str(excinfo.value)


def test_the_sandbox_cannot_reach_the_users_other_data(tmp_path):
    """Only the datasets the user shared are copied in; everything else is simply not there."""
    shared = tmp_path / "shared.csv"
    shared.write_text("a\n1\n", encoding="utf-8")
    private = tmp_path / "private.csv"
    private.write_text("ssn\n123-45-6789\n", encoding="utf-8")

    catalog = Catalog()
    (shared_ds,) = catalog.open_file(shared)
    catalog.open_file(private)  # opened in the app, but NOT shared with the assistant

    sandbox = QuerySandbox(catalog, [shared_ds.id])
    tools = ToolBox(sandbox, PrivacyLevel.SAMPLE_ROWS)
    assert list(sandbox.tables) == ["shared"]
    with pytest.raises(Exception) as excinfo:
        tools.call("run_sql", {"sql": "SELECT * FROM private"})
    assert "123-45-6789" not in str(excinfo.value)
    sandbox.close()
    catalog.close()


def test_the_sandbox_can_still_answer_honest_questions(box):
    result = json.loads(box.call("run_sql", {"sql": "SELECT region, amount FROM sales"}))
    assert result["columns"] == ["region", "amount"]
    assert sorted(result["rows"]) == [["East", 20], ["West", 10]]


def test_hostile_sql_comes_back_as_a_tool_error_not_a_crash(box):
    with pytest.raises(ToolError, match="only SELECT"):
        box.call("run_sql", {"sql": "DROP TABLE sales"})


def test_large_datasets_are_sampled_into_the_sandbox(tmp_path):
    catalog = Catalog()
    cursor = catalog.cursor()
    cursor.execute("CREATE TABLE big AS SELECT range AS n FROM range(120000)")
    from prospectra.core.catalog.catalog import Dataset

    dataset = Dataset(id="big", name="big", view_name="big", origin="synthetic")
    catalog.datasets["big"] = dataset

    sandbox = QuerySandbox(catalog, ["big"], max_rows=1000)
    info = sandbox.tables["big"]
    assert info.sampled and info.rows == 1000
    _cols, rows = sandbox.execute("SELECT count(*) FROM big")
    assert rows[0][0] == 1000  # the model sees the sample, not 120k rows
    sandbox.close()
    catalog.close()
