# 2026-07-13 (P4): A scripted provider for tests. No network, no keys — it replays a queue of
# replies and records what it was asked, so the tool loop, the privacy gate and the audit log can
# all be exercised deterministically.

from __future__ import annotations

from typing import Any

from prospectra.core.llm.base import Citation, LLMReply, Message, Provider, ToolCall, ToolSpec


class FakeProvider(Provider):
    type_name = "fake"
    display_name = "Fake (tests)"
    default_model = "fake-1"
    supports_web_search = True
    needs_api_key = False
    verified = True

    def __init__(self, replies: list[LLMReply], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []  # every request it was handed

    def complete(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        web_search: bool = False,
    ) -> LLMReply:
        payload = {
            "model": self.model,
            "system": system,
            "messages": [
                {
                    "role": m.role,
                    "text": m.text,
                    "tool_calls": [
                        {"name": c.name, "arguments": c.arguments} for c in m.tool_calls
                    ],
                    "tool_results": [
                        {"name": r.name, "content": r.content} for r in m.tool_results
                    ],
                }
                for m in messages
            ],
            "tools": [t.name for t in (tools or [])],
            "web_search": web_search,
        }
        # Same contract as the real providers: record the outbound payload before "sending".
        self.audit.record(self.type_name, self.model, payload)
        self.calls.append(payload)
        if not self.replies:
            return LLMReply(text="(no more scripted replies)")
        return self.replies.pop(0)


def tool_reply(name: str, arguments: dict[str, Any], call_id: str = "call-1") -> LLMReply:
    return LLMReply(text="", tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)])


def text_reply(text: str, citations: list[Citation] | None = None) -> LLMReply:
    return LLMReply(text=text, citations=citations or [])
