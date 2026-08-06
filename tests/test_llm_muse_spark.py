# 2026-08-05: Muse Spark ships defaults (https://api.meta.ai/v1, muse-spark-1.2) and BOTH remain
# user-editable — it doubles as the generic door to any OpenAI-compatible gateway, so the tests
# below drive it at a *custom* endpoint to prove the URL is configuration, not something baked in.
# 2026-07-14 (P6): Muse Spark — a provider the user points at themselves (endpoint + key + model).
#
# The test that matters most here is still the negative one: with the endpoint blanked out, the
# OpenAI SDK would default to api.openai.com, and this user's data would go to a vendor they never
# named. That must be impossible, not merely unlikely — so the provider refuses before a payload
# is built.
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
    assert MuseSparkProvider.verified is False  # no authenticated call made from this build
    assert MuseSparkProvider.supports_custom_endpoint is True
    assert MuseSparkProvider.default_base_url == "https://api.meta.ai/v1"
    assert MuseSparkProvider.default_model == "muse-spark-1.2"


def test_the_defaults_apply_when_the_user_supplies_nothing():
    provider = make_provider("muse_spark", api_key="k")
    assert provider.base_url == "https://api.meta.ai/v1"
    assert provider.model == "muse-spark-1.2"


def test_the_endpoint_and_model_are_configuration_not_code():
    """The whole point of this provider: any OpenAI-compatible gateway, no code change."""
    provider = make_provider(
        "muse_spark",
        api_key="k",
        base_url="https://my-gateway.internal/v1",
        model="some-other-model",
    )
    assert provider.base_url == "https://my-gateway.internal/v1"
    assert provider.model == "some-other-model"


def test_a_blanked_endpoint_refuses_rather_than_falling_back_to_openai(monkeypatch):
    """Clearing the field must not hand the user's data to api.openai.com."""
    provider = make_provider("muse_spark", api_key="k", model="muse-spark-1.2")
    monkeypatch.setattr(provider, "base_url", "")  # as if the default were unset
    with pytest.raises(LLMError, match="endpoint URL"):
        provider.complete("sys", [Message(role="user", text="hi")])


def test_without_a_model_it_says_so(monkeypatch):
    provider = make_provider(
        "muse_spark", api_key="k", base_url="https://gateway.internal.example/v1"
    )
    monkeypatch.setattr(provider, "model", "")
    with pytest.raises(LLMError, match="model id"):
        provider.complete("sys", [Message(role="user", text="hi")])


def test_without_a_key_it_says_so():
    provider = make_provider(
        "muse_spark", model="muse-spark-1.2", base_url="https://gateway.internal.example/v1"
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
                "model": "muse-spark-1.2",
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
        model="muse-spark-1.2",
        base_url="https://gateway.internal.example/v1",
        audit=audit,
    )
    reply = provider.complete("You are helpful.", [Message(role="user", text="Are you there?")])

    assert reply.text == "OK"
    assert str(seen["url"]).startswith("https://gateway.internal.example/v1/chat/completions")
    assert seen["auth"] == "Bearer sk-muse-123"
    assert seen["body"]["model"] == "muse-spark-1.2"

    # the audit rule: the payload was recorded before the call left the process
    assert audit.entries
    assert audit.entries[-1].provider == "muse_spark"
