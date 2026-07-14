# 2026-07-13 (P4): Provider contract — one small ABC every LLM backend implements, so the rest of
# the app never knows which model it is talking to. Third-party providers register via the
# `prospectra.llm_providers` entry-point group.
#
# `Message.raw` is the important subtlety: providers may return content the API requires be sent
# back *verbatim* on the next turn (Anthropic thinking blocks are the case in point). The agent
# stores that native payload here and the owning provider round-trips it unchanged; providers that
# do not need it simply ignore it.

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from prospectra.core.llm.audit import AuditLog


class LLMError(Exception):
    """Any failure talking to a provider (auth, network, bad request)."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for the tool's input


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class Citation:
    title: str
    url: str


@dataclass
class Message:
    role: str  # "user" | "assistant" | "tool"
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    raw: Any = None  # provider-native content, replayed verbatim by its owning provider


@dataclass(frozen=True)
class LLMReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    raw: Any = None
    stop_reason: str = ""


class Provider(ABC):
    type_name: ClassVar[str]
    display_name: ClassVar[str]
    default_model: ClassVar[str]
    supports_web_search: ClassVar[bool] = False
    needs_api_key: ClassVar[bool] = True
    # Honesty flag surfaced in the UI: has this provider been exercised against its live API in
    # this build? Only flip to True once a real call has been made and observed.
    verified: ClassVar[bool] = False

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        audit: AuditLog | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model or self.default_model
        self.base_url = base_url
        # Every provider MUST record its outbound payload here before the call leaves the process.
        self.audit = audit if audit is not None else AuditLog()

    @abstractmethod
    def complete(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        web_search: bool = False,
    ) -> LLMReply:
        """One round trip. Raises LLMError on failure."""
