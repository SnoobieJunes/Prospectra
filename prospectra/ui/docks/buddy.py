# 2026-07-13 (P0): Right dock — the LLM "data buddy" chat panel. Deliberately disabled until the
# provider layer, privacy gates, and safe tools land in P4; the dock exists now so the shell
# layout is final and the P4 work slots in without rearranging the window.

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget, QLabel, QLineEdit, QVBoxLayout, QWidget


class BuddyDock(QDockWidget):
    def __init__(self) -> None:
        super().__init__("Data Buddy")
        self.setObjectName("dock_buddy")
        body = QWidget()
        layout = QVBoxLayout(body)
        note = QLabel(
            "Chat with your data — arrives in phase P4.\n\n"
            "Providers: Anthropic, OpenAI, Gemini, Ollama.\n"
            "Privacy-gated: schema-only by default; the model\n"
            "queries via safe read-only tools, never raw dumps."
        )
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setWordWrap(True)
        note.setEnabled(False)
        layout.addStretch(1)
        layout.addWidget(note)
        layout.addStretch(1)
        prompt = QLineEdit()
        prompt.setPlaceholderText("Ask about your data… (enabled in P4)")
        prompt.setEnabled(False)
        layout.addWidget(prompt)
        self.setWidget(body)
