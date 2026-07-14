# 2026-07-13 (P4): OpenAI, via the official `openai` SDK (chat completions + function calling).
#
# HONESTY: the request/response *shape* is implemented, but no live call was made in this build —
# there is no OpenAI key here. `verified = False`, and the UI badges it "experimental". The model
# id is a user-editable default, not a claim about what exists.

from __future__ import annotations

import json
import logging
from typing import Any

from prospectra.core.llm.base import (
    LLMError,
    LLMReply,
    Message,
    Provider,
    ToolCall,
    ToolSpec,
)

logger = logging.getLogger(__name__)


class OpenAIProvider(Provider):
    type_name = "openai"
    display_name = "OpenAI"
    default_model = "gpt-5"
    supports_web_search = False  # not wired up here; see Deviations.md
    supports_custom_endpoint = True  # an OpenAI-compatible gateway can be pointed at by URL
    verified = False

    def _client(self) -> Any:
        import openai

        if not self.api_key and self.needs_api_key:
            raise LLMError("No OpenAI API key. Add one in Settings ▸ Data Buddy.")
        kwargs: dict[str, Any] = {"api_key": self.api_key or "not-needed"}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return openai.OpenAI(**kwargs)

    def complete(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        web_search: bool = False,
    ) -> LLMReply:
        import openai

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *_to_openai(messages)],
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]

        self.audit.record(self.type_name, self.model, payload)

        try:
            response = self._client().chat.completions.create(**payload)
        except openai.APIStatusError as exc:
            raise LLMError(f"{self.display_name} API error: {exc}") from exc
        except openai.APIConnectionError as exc:
            raise LLMError(f"Could not reach {self.display_name}: {exc}") from exc

        choice = response.choices[0].message
        calls: list[ToolCall] = []
        for call in choice.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            calls.append(ToolCall(id=call.id, name=call.function.name, arguments=arguments))
        return LLMReply(
            text=(choice.content or "").strip(),
            tool_calls=calls,
            stop_reason=str(response.choices[0].finish_reason or ""),
        )


def _to_openai(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "user":
            out.append({"role": "user", "content": message.text})
        elif message.role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": message.text or None}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                    }
                    for c in message.tool_calls
                ]
            out.append(entry)
        elif message.role == "tool":
            out.extend(
                {"role": "tool", "tool_call_id": r.call_id, "content": r.content}
                for r in message.tool_results
            )
    return out


class OllamaProvider(OpenAIProvider):
    """Ollama speaks the OpenAI chat API, so it rides the same client — pointed at localhost.

    This is the privacy-maximal option: with a local model, no data leaves the machine at all.
    """

    type_name = "ollama"
    display_name = "Ollama (local)"
    default_model = "llama3.1"
    needs_api_key = False
    supports_custom_endpoint = True
    verified = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.base_url = self.base_url or "http://localhost:11434/v1"
