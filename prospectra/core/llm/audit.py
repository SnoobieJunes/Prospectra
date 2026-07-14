# 2026-07-13 (P4): The audit log — a record of exactly what left this machine.
#
# This is the mechanism that makes the privacy gate *provable* rather than merely claimed. Every
# provider records its fully-built request payload here immediately before sending it. A test can
# then plant a sentinel value in the data, hold a whole conversation in schema-only mode, and
# assert the sentinel appears in no outbound payload. The UI shows the same log so the user can
# read, byte for byte, what was shared.

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class AuditEntry:
    when: str
    provider: str
    model: str
    payload: dict[str, Any]

    def serialized(self) -> str:
        return json.dumps(self.payload, default=str, ensure_ascii=False)


class AuditLog:
    def __init__(self, limit: int = 200) -> None:
        self._entries: deque[AuditEntry] = deque(maxlen=limit)

    def record(self, provider: str, model: str, payload: dict[str, Any]) -> AuditEntry:
        entry = AuditEntry(
            when=datetime.now(UTC).isoformat(timespec="seconds"),
            provider=provider,
            model=model,
            payload=payload,
        )
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def contains(self, needle: str) -> bool:
        """Did this string ever leave the machine? The privacy proof, in one call."""
        return any(needle in entry.serialized() for entry in self._entries)

    def transcript(self) -> str:
        return "\n\n".join(
            f"[{e.when}] {e.provider}/{e.model}\n{json.dumps(e.payload, indent=2, default=str)}"
            for e in self._entries
        )

    def clear(self) -> None:
        self._entries.clear()
