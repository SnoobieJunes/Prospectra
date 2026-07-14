# 2026-07-13 (P3): The trust light — "how much should I believe this model?" in one glance.
# Status colour is never the only signal: it always ships with a word (GOOD / CAUTION / POOR) and
# the plain-English reasons, per the accessibility rule. A high R-squared on a model whose
# assumptions are broken is the most dangerous output this app can produce, so this is loud.

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from prospectra.core.stats import Diagnostics
from prospectra.ui.widgets.charts import STATUS

_HEADLINE = {
    "good": "GOOD — this fit can be read at face value",
    "caution": "CAUTION — usable, but read the notes",
    "poor": "POOR — the assumptions behind this model are broken",
}


class TrustLight(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 6, 8, 6)
        self._title = QLabel("Run a scan to see how trustworthy its model is.")
        self._title.setWordWrap(True)
        self._layout.addWidget(self._title)
        self._notes = QLabel("")
        self._notes.setWordWrap(True)
        self._notes.setEnabled(False)
        self._layout.addWidget(self._notes)

    def set_diagnostics(self, diagnostics: Diagnostics | None) -> None:
        if diagnostics is None:
            self._title.setText("No model to check (choose a numeric target and scan).")
            self._title.setStyleSheet("")
            self._notes.setText("")
            return
        colour = STATUS[diagnostics.verdict]
        self._title.setText(f"Trust: {_HEADLINE[diagnostics.verdict]}")
        self._title.setStyleSheet(f"color: {colour}; font-weight: 600;")
        detail = list(diagnostics.notes)
        detail.append(
            f"Residual normality ({diagnostics.normality_test}): p = {diagnostics.normality_p:.3g}"
            if diagnostics.normality_p is not None
            else ""
        )
        self._notes.setText("\n".join(f"• {d}" for d in detail if d))
