# 2026-07-13 (P4): Provider registry — built-ins plus anything installed under the
# `prospectra.llm_providers` entry-point group.

from __future__ import annotations

import logging
from importlib.metadata import entry_points

from prospectra.core.llm.audit import AuditLog
from prospectra.core.llm.base import LLMError, Provider
from prospectra.core.llm.providers.anthropic_provider import AnthropicProvider
from prospectra.core.llm.providers.google_provider import GoogleProvider
from prospectra.core.llm.providers.openai_provider import OllamaProvider, OpenAIProvider

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "prospectra.llm_providers"

PROVIDERS: dict[str, type[Provider]] = {
    AnthropicProvider.type_name: AnthropicProvider,
    OpenAIProvider.type_name: OpenAIProvider,
    GoogleProvider.type_name: GoogleProvider,
    OllamaProvider.type_name: OllamaProvider,
}


def load_external_providers() -> None:
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            cls = ep.load()
        except Exception:
            logger.warning("Could not load LLM provider plugin %r", ep.name, exc_info=True)
            continue
        if isinstance(cls, type) and issubclass(cls, Provider):
            PROVIDERS.setdefault(cls.type_name, cls)


def make_provider(
    type_name: str,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    audit: AuditLog | None = None,
) -> Provider:
    cls = PROVIDERS.get(type_name)
    if cls is None:
        raise LLMError(f"Unknown provider {type_name!r}. Known: {', '.join(sorted(PROVIDERS))}")
    return cls(api_key=api_key, model=model, base_url=base_url, audit=audit)
