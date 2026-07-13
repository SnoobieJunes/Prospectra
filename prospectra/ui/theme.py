# 2026-07-13 (P0): Application-wide look & feel. Fusion gives a consistent cross-platform base
# and respects the OS light/dark palette on Qt 6.5+.
# Why: one module so a future theme system (plan: ui/theme) has a single seam to replace.

from __future__ import annotations

from PySide6.QtWidgets import QApplication


def apply(app: QApplication) -> None:
    app.setApplicationName("Prospectra")
    app.setOrganizationName("Prospectra")
    app.setStyle("Fusion")
