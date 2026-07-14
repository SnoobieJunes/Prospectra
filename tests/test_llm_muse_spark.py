# 2026-07-14 (P6): Muse Spark — a provider the user points at themselves (endpoint + key + model).
#
# The test that matters most here is the negative one: with no endpoint configured, the OpenAI SDK
# would default to api.openai.com, and this user's data would go to a vendor they never named. That
# must be impossible, not merely unlikely — so the provider refuses before a payload is built.
#
# It is also held to the rule every provider is held to (CLAUDE.md): the outbound payload is
# recorded in the audit log BEFORE the call leaves the process. A provider that skips that would
# make the privacy guarantee unverifiable.

from __future__ import annotations

import httpx
import pytest

from prospectra.core.llm import PROVIDERS, AuditLog, LLMError, Message, make_provider
from prospectra.core.llm.providers.muse_spark import MuseSparkProvider


def test_muse_spark_is_registered_and_honest_about_being_unverified():
    assert PROVIDERS["muse_spark"] is MuseSparkProvider
    assert MuseSparkProvider.verified is False  # no live endpoint called from this build
    assert MuseSparkProvider.supports_custom_endpoint is True
    assert MuseSparkProvider.default_model == ""  # nothing to guess: the user names the model


def test_without_an_endpoint_it_refuses_rather_than_falling_back_to_openai():
    provider = make_provider("muse_spark", api_key="k", model="muse-spark-meta")
    with pytest.raises(LLMError, match="endpoint URL"):
        provider.complete("sys", [Message(role="user", text="hi")])


def test_without_a_model_it_says_so():
    provider = make_provider("muse_spark", api_key="k", base_url="https://api.musespark.ai/v1")
    with pytest.raises(LLMError, match="model id"):
        provider.complete("sys", [Message(role="user", text="hi")])


def test_without_a_key_it_says_so():
    provider = make_provider(
        "muse_spark", model="muse-spark-meta", base_url="https://api.musespark.ai/v1"
    )
    with pytest.raises(LLMError, match="API key"):
        provider.complete("sys", [Message(role="user", text="hi")])


def test_it_talks_the_openai_standard_to_the_endpoint_the_user_named(monkeypatch):
    """A scripted OpenAI-compatible server: the request must go to the user's endpoint, carry the
    user's model and key, and be parsed as an OpenAI chat completion."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "muse-spark-meta",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    import openai

    real_openai = openai.OpenAI

    def fake_openai(**kwargs):  # inject a transport into the real SDK client
        kwargs["http_client"] = httpx.Client(transport=httpx.MockTransport(handler))
        return real_openai(**kwargs)

    monkeypatch.setattr(openai, "OpenAI", fake_openai)

    audit = AuditLog()
    provider = make_provider(
        "muse_spark",
        api_key="sk-muse-123",
        model="muse-spark-meta",
        base_url="https://api.musespark.ai/v1",
        audit=audit,
    )
    reply = provider.complete("You are helpful.", [Message(role="user", text="Are you there?")])

    assert reply.text == "OK"
    assert str(seen["url"]).startswith("https://api.musespark.ai/v1/chat/completions")
    assert seen["auth"] == "Bearer sk-muse-123"
    assert seen["body"]["model"] == "muse-spark-meta"

    # the audit rule: the payload was recorded before the call left the process
    assert audit.entries
    assert audit.entries[-1].provider == "muse_spark"
