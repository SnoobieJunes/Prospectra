# 2026-07-13 (P0): Bottom dock — live log view. A logging.Handler bridges Python logging into the
# widget via a Qt signal, so records emitted from worker threads (QThreadPool jobs in later
# phases) cross to the GUI thread safely through Qt's queued-connection machinery.

from __future__ import annotations

import contextlib
import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDockWidget, QPlainTextEdit


class _Bridge(QObject):
    message = Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, bridge: _Bridge) -> None:
        super().__init__()
        self._bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        # Suppress RuntimeError: the widget may already be destroyed during shutdown.
        with contextlib.suppress(RuntimeError):
            self._bridge.message.emit(self.format(record))


class LogDock(QDockWidget):
    def __init__(self) -> None:
        super().__init__("Log")
        self.setObjectName("dock_log")
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setMaximumBlockCount(5000)  # bound memory for long sessions
        self.setWidget(view)
        self._bridge = _Bridge(self)
        self._bridge.message.connect(view.appendPlainText)
        self.handler = QtLogHandler(self._bridge)
