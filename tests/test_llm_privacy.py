# 2026-07-13 (P4): The privacy guarantee, tested the only way that means anything: plant a
# sentinel value in the data, let the assistant loose on it, and assert the sentinel never appears
# in anything that left the machine.

import json

import pytest

from prospectra.core.catalog import Catalog
from prospectra.core.llm import DataBuddy, PrivacyLevel, ToolBox
from prospectra.core.llm.sandbox import QuerySandbox
from prospectra.core.llm.tools import ToolError
from tests.fake_provider import FakeProvider, text_reply, tool_reply

SENTINEL = "ZQX-SENTINEL-42"  # a value that exists in exactly one cell of the test data


@pytest.fixture()
def catalog(tmp_path):
    path = tmp_path / "customers.csv"
    path.write_text(
        f"customer,region,spend\n{SENTINEL},West,100\nbob,West,50\ncara,East,20\ndan,East,80\n",
        encoding="utf-8",
    )
    cat = Catalog()
    cat.open_file(path)
    yield cat
    cat.close()


@pytest.fixture()
def sandbox(catalog):
    box = QuerySandbox(catalog, list(catalog.datasets))
    yield box
    box.close()


def _buddy(sandbox, privacy, replies):
    provider = FakeProvider(replies)
    return DataBuddy(provider, ToolBox(sandbox, privacy), privacy), provider


# -- the guarantee ---------------------------------------------------------------------------


def test_schema_only_never_sends_a_single_value(sandbox):
    """The load-bearing test. In schema-only mode, an assistant that tries every tool it can
    think of must still never get — and therefore never transmit — a data value."""
    buddy, provider = _buddy(
        sandbox,
        PrivacyLevel.SCHEMA_ONLY,
        [
            tool_reply("list_datasets", {}),
            tool_reply("describe_dataset", {"table": "customers"}),
            tool_reply("run_sql", {"sql": "SELECT customer FROM customers"}),  # should be refused
            tool_reply("column_stats", {"table": "customers", "column": "customer"}),  # refused
            text_reply("I can only see your column names at this sharing level."),
        ],
    )
    reply = buddy.ask("What is in my data?")

    # The sentinel never left the machine — this is the whole promise, and it is checkable.
    assert not provider.audit.contains(SENTINEL)
    assert not provider.audit.contains("cara")  # nor any other cell value
    # The refused tools were not merely blocked — they were never offered.
    offered = set(provider.calls[0]["tools"])
    assert offered == {"list_datasets", "describe_dataset"}
    assert "run_sql" not in offered
    # The trail says REFUSED, so a blocked call can never read to the user as a successful one.
    refused = [entry for entry in reply.tool_trail if "refused" in entry]
    assert len(refused) == 2
    assert any("run_sql" in entry for entry in refused)
    assert "not available at the current privacy level" in " ".join(refused)


def test_aggregates_sends_summaries_but_never_a_row(sandbox):
    buddy, provider = _buddy(
        sandbox,
        PrivacyLevel.AGGREGATES,
        [
            tool_reply(
                "aggregate",
                {
                    "table": "customers",
                    "group_by": ["region"],
                    "metrics": [{"function": "sum", "column": "spend"}],
                },
            ),
            tool_reply("run_sql", {"sql": "SELECT customer FROM customers"}),  # not offered
            text_reply("West spends more than East."),
        ],
    )
    buddy.ask("Which region spends more?")

    # Aggregates did go out…
    assert provider.audit.contains("150")  # West's total spend
    # …but no individual customer ever did.
    assert not provider.audit.contains(SENTINEL)
    assert not provider.audit.contains("cara")
    assert "run_sql" not in set(provider.calls[0]["tools"])


def test_sample_rows_is_the_only_level_that_can_see_a_row(sandbox):
    buddy, provider = _buddy(
        sandbox,
        PrivacyLevel.SAMPLE_ROWS,
        [
            tool_reply("run_sql", {"sql": "SELECT customer FROM customers ORDER BY spend DESC"}),
            text_reply("Your biggest spender is the first row."),
        ],
    )
    buddy.ask("Who spends the most?")
    assert "run_sql" in set(provider.calls[0]["tools"])
    assert provider.audit.contains(SENTINEL)  # the user explicitly allowed this


# -- the gate itself --------------------------------------------------------------------------


def test_tools_are_filtered_by_level(sandbox):
    names = lambda level: {s.name for s in ToolBox(sandbox, level).specs()}  # noqa: E731
    assert names(PrivacyLevel.SCHEMA_ONLY) == {"list_datasets", "describe_dataset"}
    assert "aggregate" in names(PrivacyLevel.AGGREGATES)
    assert "run_sql" not in names(PrivacyLevel.AGGREGATES)
    assert "run_sql" in names(PrivacyLevel.SAMPLE_ROWS)


def test_calling_a_forbidden_tool_directly_is_refused(sandbox):
    box = ToolBox(sandbox, PrivacyLevel.AGGREGATES)
    with pytest.raises(ToolError, match="privacy level"):
        box.call("run_sql", {"sql": "SELECT * FROM customers"})


def test_aggregate_cannot_be_coerced_into_returning_rows(sandbox):
    """The aggregate tool takes structured params, not SQL — there is no way to ask it for a row."""
    box = ToolBox(sandbox, PrivacyLevel.AGGREGATES)
    with pytest.raises(ToolError, match="metric must be one of"):
        box.call(
            "aggregate",
            {"table": "customers", "metrics": [{"function": "first", "column": "customer"}]},
        )
    result = json.loads(
        box.call("aggregate", {"table": "customers", "metrics": [{"function": "count"}]})
    )
    assert result["rows"] == [[4]]  # a count, not a customer


def test_unknown_column_is_reported_back_to_the_model(sandbox):
    box = ToolBox(sandbox, PrivacyLevel.AGGREGATES)
    with pytest.raises(ToolError, match="no column"):
        box.call("column_stats", {"table": "customers", "column": "ghost"})
