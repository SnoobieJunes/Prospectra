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
    # 2026-07-14 (P5): the real DashboardTab is passed in as an override by the main window.
    ("Dashboards", "Dashboards — drag columns onto chart shelves."),
    # 2026-07-31 (P7): the API playground — explore an endpoint, then save it as a data source.
    ("API", "API playground — explore an endpoint, save requests, promote them to data sources."),
)


def _placeholder_page(text: str) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setEnabled(False)  # muted, so it reads as a placeholder rather than content
    layout.addWidget(label)
    return page


# 2026-07-13 (P1): `overrides` lets phases swap a placeholder for the real workspace widget
# without touching the shell layout (Data lands in P1, Flow in P2, …).
def make_central(overrides: dict[str, QWidget] | None = None) -> QTabWidget:
    tabs = QTabWidget()
    tabs.setObjectName("central_tabs")
    tabs.setDocumentMode(True)
    overrides = overrides or {}
    for title, text in _PLACEHOLDERS:
        tabs.addTab(overrides.get(title) or _placeholder_page(text), title)
    return tabs
