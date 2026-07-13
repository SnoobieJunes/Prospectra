# 2026-07-13 (P0): GUI bootstrap — builds the QApplication, applies the theme, wires the UI log
# dock into core logging, and shows the main window.
# Why: kept separate from cli.py so headless commands never import Qt (import-linter guarantees
# core independence; this module is the single place Qt startup lives).

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from prospectra import __version__
from prospectra.core import log as core_log
from prospectra.ui import theme
from prospectra.ui.main_window import MainWindow

logger = logging.getLogger("prospectra")


def run_gui(smoke: bool = False) -> int:
    """Launch the GUI. With smoke=True, auto-quit after ~2.5 s (CI launch check)."""
    app = QApplication(sys.argv[:1])
    theme.apply(app)
    window = MainWindow()
    core_log.configure(extra_handlers=[window.log_handler])
    window.show()
    logger.info("Prospectra %s ready (smoke=%s)", __version__, smoke)
    if smoke:
        QTimer.singleShot(2500, app.quit)
    return int(app.exec())
