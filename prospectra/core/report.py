# 2026-08-05: What every write reports, in a module that imports NOTHING from the rest of core.
#
# It lived in core/flow/write.py, which made `import prospectra.core.http.write` crash on a cold
# interpreter: core.http.write -> core.flow.write -> core.flow.__init__ (which eagerly imports
# every node) -> nodes.output_rest -> back into the half-initialised core.http.write. The test
# suite never saw it because the tests happen to import core.flow first. The layering fix is the
# real one: HTTP is a lower layer than the flow engine, so the shared value type belongs beneath
# both rather than inside one of them.

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RowFailure:
    """One row that did not land — enough to find it, judge it, and re-run it."""

    index: int  # 0-based position in the written set
    key: str  # the row's key-column value ("" when the write has no key column)
    status: int  # HTTP status for REST writes; 0 for local failures
    message: str


@dataclass
class WriteReport:
    """The result of one output node's write. Aliased as `OutputResult` for pre-P7 callers."""

    attempted: int = 0
    written: int = 0
    failed: int = 0
    skipped: int = 0
    dry_run: bool = False
    stopped_early: bool = False
    failures: list[RowFailure] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    node_id: str = ""
    path: str = ""  # file destinations; "" for others

    @property
    def rows(self) -> int:
        """Pre-P7 name for "rows written" — `cli.py` and the P2 tests read this."""
        return self.written

    @property
    def ok(self) -> bool:
        return self.failed == 0 and not self.stopped_early
