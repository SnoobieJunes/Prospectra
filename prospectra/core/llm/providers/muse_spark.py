# 2026-07-14 (P6): Muse Spark — a provider you point at yourself.
#
# It speaks the OpenAI chat-completions standard, so it reuses OpenAIProvider's request/response
# handling wholesale (the same reason Ollama does). What makes it its own provider rather than
# "OpenAI with a different base URL" is that all three of endpoint, key, and model are **required
# and user-supplied**: there is no default endpoint to fall back on and no default model to guess.
# A silent fallback to api.openai.com would be the worst possible failure here — the user's data
# would go somewhere they did not name.
#
# So the checks are up-front and specific, before any payload is built:
#   * no base URL   -> "paste the endpoint URL", not a 404 from somebody else's server;
#   * no model      -> "name the model", not a 400 from the endpoint;
#   * no API key    -> the same keychain-backed message every other provider gives.
#
# HONESTY: `verified = False`. The OpenAI-standard request shape is implemented and tested against
# a scripted server, but no live Muse Spark endpoint has been called from this build, so the UI
# badges it "experimental" — same rule as the other four providers (CLAUDE.md).

from __future__ import annotations

import logging
from typing import Any

from prospectra.core.llm.base import LLMError
from prospectra.core.llm.providers.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


class MuseSparkProvider(OpenAIProvider):
    """A custom OpenAI-compatible endpoint: you supply the URL, the key, and the model."""

    type_name = "muse_spark"
    display_name = "Muse Spark (custom OpenAI-compatible endpoint)"
    default_model = ""  # no default: the endpoint's models are not knowable from here
    needs_api_key = True
    supports_custom_endpoint = True
    supports_web_search = False
    verified = False

    setup_hint = (
        "Muse Spark uses the OpenAI API standard. Fill in all three:\n"
        "  • Base URL — the endpoint's OpenAI-compatible root, e.g. "
        "https://api.musespark.ai/v1\n"
        "  • API key — stored in your OS keychain, never in the project file\n"
        "  • Model — the model id the endpoint serves, e.g. muse-spark-meta"
    )

    def _client(self) -> Any:
        # Fail on the missing *setting*, not on the HTTP response it would produce. Without a base
        # URL the OpenAI SDK would happily talk to api.openai.com — sending this user's data to a
        # vendor they never named. That must be impossible, not merely unlikely.
        if not self.base_url:
            raise LLMError(
                "Muse Spark needs its endpoint URL. Add it under Base URL in "
                "Settings ▸ Data Buddy (e.g. https://api.musespark.ai/v1)."
            )
        if not self.model:
            raise LLMError(
                "Muse Spark needs a model id. Add it under Model in Settings ▸ Data Buddy — "
                "the endpoint's provider will tell you what it serves."
            )
        if not self.api_key:
            raise LLMError("No Muse Spark API key. Add one in Settings ▸ Data Buddy.")
        return super()._client()
