# 2026-07-13 (P4): Anthropic (Claude) — the reference provider, and the only one with server-side
# web search, which is what lets the hypothesis engine return *cited* explanations.
#
# Two details that are easy to get wrong and are deliberate here:
#  * The assistant's raw content blocks are replayed verbatim on the next turn (Message.raw).
#    Adaptive thinking blocks must go back unchanged or the API rejects the turn; rebuilding them
#    from our neutral Message type would corrupt them.
#  * Web search results arrive as `web_search_tool_result` blocks and citations ride on the text
#    blocks; on failure that block's content is an error *object*, not a list — so we check.

from __future__ import annotations

import logging
from typing import Any

from prospectra.core.llm.base import (
    Citation,
    LLMError,
    LLMReply,
    Message,
    Provider,
    ToolCall,
    ToolSpec,
)

logger = logging.getLogger(__name__)

MAX_TOKENS = 16_000
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 6}


class AnthropicProvider(Provider):
    type_name = "anthropic"
    display_name = "Anthropic (Claude)"
    default_model = "claude-opus-4-8"
    supports_web_search = True
    verified = False  # no API key in this build — see Deviations.md

    def _client(self) -> Any:
        import anthropic

        if not self.api_key:
            raise LLMError("No Anthropic API key. Add one in Settings ▸ Data Buddy.")
        return anthropic.Anthropic(api_key=self.api_key)

    def complete(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        web_search: bool = False,
    ) -> LLMReply:
        import anthropic

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": system,
            "messages": _to_anthropic(messages),
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": "high"},
        }
        spec_tools: list[dict[str, Any]] = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in (tools or [])
        ]
        if web_search:
            spec_tools.append(dict(WEB_SEARCH_TOOL))
        if spec_tools:
            payload["tools"] = spec_tools

        # Everything that leaves this machine is recorded first — this is the privacy proof.
        self.audit.record(self.type_name, self.model, payload)

        try:
            response = self._client().messages.create(**payload)
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"Could not reach the Anthropic API: {exc}") from exc

        if response.stop_reason == "refusal":
            raise LLMError("Claude declined this request.")
        return _parse(response)


def _to_anthropic(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "user":
            out.append({"role": "user", "content": message.text})
        elif message.role == "assistant":
            # Replay the native blocks unchanged (thinking blocks must not be rebuilt).
            if message.raw is not None:
                out.append({"role": "assistant", "content": message.raw})
            else:
                out.append({"role": "assistant", "content": message.text})
        elif message.role == "tool":
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": r.call_id,
                            "content": r.content,
                            **({"is_error": True} if r.is_error else {}),
                        }
                        for r in message.tool_results
                    ],
                }
            )
    return out


def _parse(response: Any) -> LLMReply:
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    citations: list[Citation] = []

    for block in response.content:
        kind = getattr(block, "type", "")
        if kind == "text":
            text_parts.append(block.text)
            for citation in getattr(block, "citations", None) or []:
                url = getattr(citation, "url", None)
                if url:
                    citations.append(Citation(title=getattr(citation, "title", "") or url, url=url))
        elif kind == "tool_use":
            tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input)))
        elif kind == "web_search_tool_result":
            # On failure `.content` is an error object, not a list of results.
            content = getattr(block, "content", None)
            if isinstance(content, list):
                for result in content:
                    url = getattr(result, "url", None)
                    if url:
                        citations.append(
                            Citation(title=getattr(result, "title", "") or url, url=url)
                        )
            else:
                logger.warning(
                    "Web search failed: %s", getattr(content, "error_code", "unknown error")
                )

    return LLMReply(
        text="\n".join(p for p in text_parts if p).strip(),
        tool_calls=tool_calls,
        citations=_dedupe(citations),
        raw=response.content,
        stop_reason=str(response.stop_reason or ""),
    )


def _dedupe(citations: list[Citation]) -> list[Citation]:
    seen: dict[str, Citation] = {}
    for citation in citations:
        seen.setdefault(citation.url, citation)
    return list(seen.values())
