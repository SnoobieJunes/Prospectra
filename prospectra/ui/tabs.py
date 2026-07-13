# 2026-07-13 (P0): Central tab widget with honest placeholders for the four workspaces.
# Why: fixes the app's information architecture (Flow / Data / Analyze / Dashboards) now so each
# later phase replaces a placeholder instead of rearranging the shell; labels state which phase
# delivers them rather than pretending features exist.

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

_PLACEHOLDERS: tuple[tuple[str, str], ...] = (
    ("Flow", "Prep flow canvas — arrives in phase P2.\nInputs → clean → join/union → output."),
    ("Data", "Data grid & column profiler — arrives in phase P1."),
    ("Analyze", "Mining engine — arrives in phase P3.\nCorrelation scan, regressions, ANOVA, PCA."),
    ("Dashboards", "Dashboards — arrive in phase P5."),
)


def _placeholder_page(text: str) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setEnabled(False)  # muted, so it reads as a placeholder rather than content
    layout.addWidget(label)
    return page


def make_central() -> QTabWidget:
    tabs = QTabWidget()
    tabs.setObjectName("central_tabs")
    tabs.setDocumentMode(True)
    for title, text in _PLACEHOLDERS:
        tabs.addTab(_placeholder_page(text), title)
    return tabs
