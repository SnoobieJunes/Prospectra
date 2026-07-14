# 2026-07-13 (P4): The tool loop — provider-agnostic. Ask → the model may call tools → we run them
# through the gate → feed results back → repeat until it answers.
#
# The system prompt does two jobs beyond the obvious: it tells the model what it may and may not
# see (so it stops guessing at data it cannot reach), and it forbids causal language. A tool that
# says "temperature drives sales" would be worse than useless — every correlation the mining
# engine finds is an association, and the whole app is careful about that. The assistant must be
# too.

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from prospectra.core.llm.base import (
    Citation,
    LLMError,
    Message,
    Provider,
    ToolResult,
)
from prospectra.core.llm.privacy import PrivacyLevel
from prospectra.core.llm.tools import ToolBox, ToolError

logger = logging.getLogger(__name__)

MAX_STEPS = 8

SYSTEM = """You are Prospectra's data buddy, helping someone understand their own dataset.

WHAT YOU CAN SEE
You have no direct access to the data. Everything you learn comes from the tools below, and the
user has set the sharing level to: {privacy_label}.
{privacy_explanation}
Never guess at values you cannot see. If a tool you need is not available, say so and tell the
user which sharing level would provide it.

HOW TO ANSWER
- Look before you answer: call the tools rather than speculating. Start with list_datasets and
  describe_dataset.
- Correlation is not causation, and you must never imply otherwise. Say "moves with", "is
  associated with", "differs across". Never say one column "causes", "drives", or "leads to"
  another. When you suggest an explanation, label it as a hypothesis and offer the competing ones
  — especially a confounder that could produce the pattern without any causal link.
- Numbers came from a sample: say so when it matters.
- Be concrete and brief. Plain English, not statistics jargon; when you must use a term, define it
  in the same breath.
"""


@dataclass
class BuddyReply:
    text: str
    citations: list[Citation] = field(default_factory=list)
    tool_trail: list[str] = field(default_factory=list)  # what it looked at, for the UI
    steps: int = 0


class DataBuddy:
    def __init__(self, provider: Provider, tools: ToolBox, privacy: PrivacyLevel) -> None:
        self.provider = provider
        self.tools = tools
        self.privacy = privacy
        self.history: list[Message] = []

    def system_prompt(self) -> str:
        return SYSTEM.format(
            privacy_label=self.privacy.label,
            privacy_explanation=self.privacy.explanation,
        )

    def ask(self, question: str, max_steps: int = MAX_STEPS) -> BuddyReply:
        self.history.append(Message(role="user", text=question))
        trail: list[str] = []
        specs = self.tools.specs()

        for step in range(1, max_steps + 1):
            reply = self.provider.complete(self.system_prompt(), self.history, specs)
            self.history.append(
                Message(
                    role="assistant",
                    text=reply.text,
                    tool_calls=list(reply.tool_calls),
                    raw=reply.raw,
                )
            )
            if not reply.tool_calls:
                return BuddyReply(
                    text=reply.text, citations=list(reply.citations), tool_trail=trail, steps=step
                )

            results: list[ToolResult] = []
            for call in reply.tool_calls:
                label = _describe_call(call.name, call.arguments)
                try:
                    content = self.tools.call(call.name, call.arguments)
                    trail.append(label)
                    results.append(ToolResult(call.id, call.name, content))
                except ToolError as exc:
                    # The trail must say REFUSED, not just list the tool — otherwise a blocked
                    # call reads to the user as though the assistant saw the data.
                    logger.info("Tool %s refused: %s", call.name, exc)
                    trail.append(f"{label} — refused ({exc})")
                    results.append(ToolResult(call.id, call.name, str(exc), is_error=True))
                except Exception as exc:  # a bug in a tool must not kill the conversation
                    logger.error("Tool %s failed: %s", call.name, exc, exc_info=True)
                    trail.append(f"{label} — failed")
                    results.append(
                        ToolResult(call.id, call.name, f"tool failed: {exc}", is_error=True)
                    )
            self.history.append(Message(role="tool", tool_results=results))

        raise LLMError(
            f"The assistant kept calling tools without answering ({max_steps} steps). "
            "Try a narrower question."
        )


def _describe_call(name: str, arguments: dict[str, object]) -> str:
    if not arguments:
        return name
    return f"{name}({json.dumps(arguments, default=str)[:120]})"
