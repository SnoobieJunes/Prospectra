# 2026-07-13 (P4): The tool loop, the audit log, keychain storage, and the hypothesis engine —
# all against the scripted fake provider, so no key and no network are needed.

import pytest

from prospectra.core.catalog import Catalog
from prospectra.core.explain import explain_finding
from prospectra.core.llm import (
    AuditLog,
    Citation,
    DataBuddy,
    LLMError,
    PrivacyLevel,
    ToolBox,
    make_provider,
)
from prospectra.core.llm.sandbox import QuerySandbox
from prospectra.core.mining import Finding
from tests.fake_provider import FakeProvider, text_reply, tool_reply


@pytest.fixture()
def tools(tmp_path):
    path = tmp_path / "sales.csv"
    path.write_text("region,amount\nWest,10\nWest,30\nEast,20\n", encoding="utf-8")
    catalog = Catalog()
    catalog.open_file(path)
    sandbox = QuerySandbox(catalog, list(catalog.datasets))
    yield ToolBox(sandbox, PrivacyLevel.AGGREGATES)
    sandbox.close()
    catalog.close()


# -- the loop ---------------------------------------------------------------------------------


def test_the_loop_runs_tools_then_answers(tools):
    provider = FakeProvider(
        [
            tool_reply("describe_dataset", {"table": "sales"}),
            tool_reply(
                "aggregate",
                {
                    "table": "sales",
                    "group_by": ["region"],
                    "metrics": [{"function": "sum", "column": "amount"}],
                },
            ),
            text_reply("West totals 40, East totals 20."),
        ]
    )
    buddy = DataBuddy(provider, tools, PrivacyLevel.AGGREGATES)
    reply = buddy.ask("Which region sells more?")

    assert reply.text == "West totals 40, East totals 20."
    assert reply.steps == 3
    assert [t.split("(")[0] for t in reply.tool_trail] == ["describe_dataset", "aggregate"]
    # the tool's real output reached the model
    last_request = provider.calls[-1]
    assert any("40" in str(m["tool_results"]) for m in last_request["messages"])


def test_a_failing_tool_is_reported_back_to_the_model_not_raised(tools):
    provider = FakeProvider(
        [
            tool_reply("column_stats", {"table": "sales", "column": "ghost"}),  # no such column
            text_reply("That column does not exist — the columns are region and amount."),
        ]
    )
    buddy = DataBuddy(provider, tools, PrivacyLevel.AGGREGATES)
    reply = buddy.ask("Summarise ghost")

    assert "does not exist" in reply.text
    errors = [
        r
        for m in provider.calls[-1]["messages"]
        for r in m["tool_results"]
        if "no column" in r["content"]
    ]
    assert errors  # the model was told what went wrong, so it could recover


def test_a_runaway_tool_loop_is_stopped(tools):
    provider = FakeProvider([tool_reply("list_datasets", {}) for _ in range(20)])
    buddy = DataBuddy(provider, tools, PrivacyLevel.AGGREGATES)
    with pytest.raises(LLMError, match="kept calling tools"):
        buddy.ask("go forever", max_steps=4)


def test_the_system_prompt_forbids_causal_language(tools):
    buddy = DataBuddy(FakeProvider([]), tools, PrivacyLevel.AGGREGATES)
    prompt = buddy.system_prompt()
    assert "Correlation is not causation" in prompt
    assert "never say" in prompt.lower()
    assert buddy.privacy.label in prompt  # the model is told what it may see


# -- the audit log ------------------------------------------------------------------------------


def test_the_audit_log_records_every_outbound_request(tools):
    audit = AuditLog()
    provider = FakeProvider([text_reply("hi")], audit=audit)
    DataBuddy(provider, tools, PrivacyLevel.AGGREGATES).ask("hello there")

    (entry,) = audit.entries
    assert entry.provider == "fake"
    assert "hello there" in entry.serialized()
    assert audit.contains("hello there")
    assert not audit.contains("something never sent")
    assert "fake" in audit.transcript()


# -- secrets ------------------------------------------------------------------------------------


def test_api_keys_go_to_the_os_keychain(monkeypatch):
    import keyring

    from prospectra.core.llm import secrets

    vault: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(keyring, "set_password", lambda s, u, p: vault.__setitem__((s, u), p))
    monkeypatch.setattr(keyring, "get_password", lambda s, u: vault.get((s, u)))

    secrets.set_api_key("anthropic", "sk-test-123")
    assert secrets.get_api_key("anthropic") == "sk-test-123"
    assert vault[(secrets.SERVICE, "anthropic")] == "sk-test-123"  # in the keychain, not a file


# -- providers ----------------------------------------------------------------------------------


def test_every_shipped_provider_can_be_constructed():
    for name in ("anthropic", "openai", "google", "ollama"):
        provider = make_provider(name, api_key="x")
        assert provider.default_model
        assert provider.display_name
    with pytest.raises(LLMError, match="Unknown provider"):
        make_provider("nope")


def test_ollama_defaults_to_localhost_and_needs_no_key():
    ollama = make_provider("ollama")
    assert ollama.base_url.startswith("http://localhost")
    assert ollama.needs_api_key is False  # local model: nothing leaves the machine


def test_only_anthropic_claims_web_search_in_this_build():
    assert make_provider("anthropic").supports_web_search is True
    assert make_provider("openai").supports_web_search is False


# -- the hypothesis engine ------------------------------------------------------------------------


def _finding() -> Finding:
    return Finding(
        kind="correlation",
        title="temperature_c ↔ ice_cream_sales",
        headline="When temperature_c goes up, ice_cream_sales tends to rise (r = +0.85).",
        columns=["temperature_c", "ice_cream_sales"],
        effect=0.85,
        effect_name="|r|",
        p_value=1e-300,
        q_value=1e-299,
        n=1095,
    )


def test_explain_finding_returns_cited_hypotheses():
    citation = Citation(title="Seasonality of ice cream demand", url="https://example.org/a")
    provider = FakeProvider(
        [
            text_reply(
                "Warm weather plausibly increases demand; school holidays may confound.",
                citations=[citation],
            )
        ]
    )
    result = explain_finding(provider, _finding(), dataset_name="ice cream")

    assert result.searched_web is True  # the fake advertises web search, like Anthropic
    assert result.citations == [citation]
    assert "confound" in result.text
    assert "cannot show what causes it" in result.disclaimer

    # Only the finding's summary went out — no rows, and the model was told to name a confounder.
    request = provider.calls[0]
    assert request["web_search"] is True
    assert "CONFOUNDER" in request["system"]
    assert "Never assert that one column causes another" in request["system"]


def test_explain_finding_without_web_search_says_so():
    provider = FakeProvider([text_reply("Some hypotheses.")])
    provider.__class__.supports_web_search = False
    try:
        result = explain_finding(provider, _finding())
        assert result.searched_web is False
        assert result.citations == []
    finally:
        provider.__class__.supports_web_search = True
