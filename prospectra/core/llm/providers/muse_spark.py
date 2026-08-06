# 2026-08-05: Muse Spark now ships real defaults — endpoint https://api.meta.ai/v1 and model
# muse-spark-1.2 — and BOTH stay editable in Settings ▸ Data Buddy. That is the point: this
# provider is also the generic door for any OpenAI-compatible gateway, so pointing Prospectra at
# your own endpoint is a settings change, never a code change. The defaults live in
# `default_base_url` / `default_model`, which the settings form reads from the class (no
# provider-name special cases anywhere in the UI).
#
# The previous defaults advertised `https://api.musespark.ai/v1`, a hostname that does not
# resolve — the app was instructing users to paste an endpoint that could never answer.
#
# 2026-07-14 (P6): It speaks the OpenAI chat-completions standard, so it reuses OpenAIProvider's
# request/response handling wholesale (the same reason Ollama does).
#
# The checks stay up-front and specific, before any payload is built:
#   * no base URL   -> refuse, rather than let the OpenAI SDK fall back to api.openai.com and
#                      send this user's data to a vendor they never named;
#   * no model      -> "name the model", not a 400 from the endpoint;
#   * no API key    -> the same keychain-backed message every other provider gives.
#
# HONESTY: `verified = False`. The request/response shape is implemented and exercised against a
# scripted OpenAI-compatible server (observed working). `api.meta.ai` resolves and answers
# `/v1/models` with HTTP 401 — i.e. it is reachable and wants a credential — but no authenticated
# call has been made from this build, so the UI badges it "experimental" (CLAUDE.md).

from __future__ import annotations

import logging
from typing import Any

from prospectra.core.llm.base import LLMError
from prospectra.core.llm.providers.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


class MuseSparkProvider(OpenAIProvider):
    """A custom OpenAI-compatible endpoint: you supply the URL, the key, and the model."""

    type_name = "muse_spark"
    display_name = "Muse Spark (OpenAI-compatible endpoint)"
    default_base_url = "https://api.meta.ai/v1"
    default_model = "muse-spark-1.2"
    needs_api_key = True
    supports_custom_endpoint = True
    supports_web_search = False
    verified = False

    setup_hint = (
        "Muse Spark uses the OpenAI API standard.\n"
        "  • Base URL — prefilled with https://api.meta.ai/v1. Replace it with any other "
        "OpenAI-compatible endpoint (your own gateway, a self-hosted server) — no code change "
        "needed.\n"
        "  • Model — prefilled with muse-spark-1.2; change it to whatever your endpoint serves.\n"
        "  • API key — stored in your OS keychain, never in the project file."
    )

    def _client(self) -> Any:
        # Fail on the missing *setting*, not on the HTTP response it would produce. Without a base
        # URL the OpenAI SDK would happily talk to api.openai.com — sending this user's data to a
        # vendor they never named. That must be impossible, not merely unlikely.
        if not self.base_url:
            raise LLMError(
                "Muse Spark needs its endpoint URL. Add it under Base URL in "
                f"Settings ▸ Data Buddy (the default is {self.default_base_url})."
            )
        if not self.model:
            raise LLMError(
                "Muse Spark needs a model id. Add it under Model in Settings ▸ Data Buddy — "
                "the endpoint's provider will tell you what it serves."
            )
        if not self.api_key:
            raise LLMError("No Muse Spark API key. Add one in Settings ▸ Data Buddy.")
        return super()._client()
