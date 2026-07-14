# 2026-07-14 (P5): The findings table, as a drag source. Drag a relationship into the chat dock and
# ask "why might this be?" without retyping it — the chip carries the finding's numbers (effect,
# q-value) so the assistant is arguing about the actual result, not a paraphrase of it.

from __future__ import annotations

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QTableWidget

from prospectra.core.mining import Finding
from prospectra.ui.dnd.mime import FindingPayload, finding_mime


class FindingsTable(QTableWidget):
    def __init__(self, rows: int = 0, columns: int = 0) -> None:
        super().__init__(rows, columns)
        self.setDragEnabled(True)
        self.setDragDropMode(QTableWidget.DragDropMode.DragOnly)
        self._findings: list[Finding] = []

    def set_findings(self, findings: list[Finding]) -> None:
        self._findings = findings

    def finding_at(self, row: int) -> Finding | None:
        return self._findings[row] if 0 <= row < len(self._findings) else None

    def mimeData(self, items):
        rows = sorted({item.row() for item in items})
        finding = self.finding_at(rows[0]) if rows else None
        if finding is None:
            return super().mimeData(items)
        return finding_mime(
            FindingPayload(
                kind=finding.kind,
                title=finding.title,
                headline=finding.headline,
                columns=list(finding.columns),
                effect=finding.effect,
                effect_name=finding.effect_name,
                q_value=finding.q_value,
            )
        )

    def mimeData_for_row(self, row: int):  # test/automation seam — no synthetic Qt drag needed
        finding = self.finding_at(row)
        if finding is None:
            return None
        return self.mimeData([self.model().index(row, 0)] if self.model() else [QModelIndex()])
