# 2026-07-13 (P4): Google Gemini, via the official `google-genai` SDK.
#
# HONESTY: shape only — no live call was made in this build (no key available), so
# `verified = False` and the UI badges it "experimental". See Deviations.md.

from __future__ import annotations

import logging
import uuid
from typing import Any, cast

from prospectra.core.llm.base import (
    LLMError,
    LLMReply,
    Message,
    Provider,
    ToolCall,
    ToolSpec,
)

logger = logging.getLogger(__name__)


class GoogleProvider(Provider):
    type_name = "google"
    display_name = "Google Gemini"
    default_model = "gemini-2.5-pro"
    supports_web_search = False  # grounding exists but is unverified here; see Deviations.md
    verified = False

    def complete(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        web_search: bool = False,
    ) -> LLMReply:
        from google import genai
        from google.genai import types

        if not self.api_key:
            raise LLMError("No Google API key. Add one in Settings ▸ Data Buddy.")

        contents = _to_gemini(messages)
        # google-genai's signatures want its own typed Schema/Content objects, but the SDK accepts
        # and converts plain dicts at runtime. Cast at the boundary rather than duplicating the
        # whole schema model in our types.
        declarations = [
            types.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters=cast(Any, t.parameters),
            )
            for t in (tools or [])
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=declarations)] if declarations else None,
        )

        self.audit.record(
            self.type_name,
            self.model,
            {
                "model": self.model,
                "system_instruction": system,
                "contents": contents,
                "tools": [t.name for t in (tools or [])],
            },
        )

        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model, contents=cast(Any, contents), config=config
            )
        except Exception as exc:  # google-genai raises its own error hierarchy
            raise LLMError(f"Gemini API error: {exc}") from exc

        calls = [
            ToolCall(
                id=uuid.uuid4().hex,  # Gemini function calls carry no id; we mint one
                name=call.name or "",
                arguments=dict(call.args or {}),
            )
            for call in (response.function_calls or [])
        ]
        return LLMReply(text=(response.text or "").strip(), tool_calls=calls)


def _to_gemini(messages: list[Message]) -> list[dict[str, Any]]:
    """Gemini uses roles user/model, with function responses as parts."""
    out: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "user":
            out.append({"role": "user", "parts": [{"text": message.text}]})
        elif message.role == "assistant":
            parts: list[dict[str, Any]] = []
            if message.text:
                parts.append({"text": message.text})
            parts.extend(
                {"function_call": {"name": c.name, "args": c.arguments}} for c in message.tool_calls
            )
            out.append({"role": "model", "parts": parts or [{"text": ""}]})
        elif message.role == "tool":
            out.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "function_response": {
                                "name": r.name,
                                "response": {"result": r.content},
                            }
                        }
                        for r in message.tool_results
                    ],
                }
            )
    return out
