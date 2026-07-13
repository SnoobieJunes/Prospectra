# 2026-07-13 (P0): Main window shell — central workspace tabs plus the three docks, and the
# File menu wired to the real project store (New/Open .prospectra files work today).
# Why: fixing the shell and the project lifecycle first means every later phase adds content to
# an existing frame instead of reshaping the app.

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox

from prospectra import __version__
from prospectra.core.project import ProjectStore, ProjectStoreError
from prospectra.ui.docks.buddy import BuddyDock
from prospectra.ui.docks.log_view import LogDock, QtLogHandler
from prospectra.ui.docks.sources import SourcesDock
from prospectra.ui.tabs import make_central

logger = logging.getLogger(__name__)

_FILE_FILTER = "Prospectra project (*.prospectra)"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Prospectra")
        self.resize(1280, 800)
        self._store: ProjectStore | None = None

        self.setCentralWidget(make_central())
        self._sources = SourcesDock()
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._sources)
        self._buddy = BuddyDock()
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._buddy)
        self._log = LogDock()
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log)

        self._build_menus()
        self.statusBar().showMessage("No project open — File ▸ New Project…")

    @property
    def log_handler(self) -> QtLogHandler:
        return self._log.handler

    # -- menus ---------------------------------------------------------------------

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        new_action = QAction("&New Project…", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self._new_project)
        file_menu.addAction(new_action)
        open_action = QAction("&Open Project…", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._open_project)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("&Help")
        about_action = QAction("&About Prospectra", self)
        about_action.triggered.connect(self._about)
        help_menu.addAction(about_action)

    # -- project lifecycle ----------------------------------------------------------

    def _new_project(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, "New Prospectra project", str(Path.home() / "Untitled.prospectra"), _FILE_FILTER
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix != ".prospectra":
            path = path.with_suffix(".prospectra")
        try:
            self._attach(ProjectStore.create(path))
        except ProjectStoreError as exc:
            QMessageBox.warning(self, "Could not create project", str(exc))

    def _open_project(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open Prospectra project", str(Path.home()), _FILE_FILTER
        )
        if not filename:
            return
        try:
            self._attach(ProjectStore.open(Path(filename)))
        except ProjectStoreError as exc:
            QMessageBox.warning(self, "Could not open project", str(exc))

    def _attach(self, store: ProjectStore) -> None:
        if self._store is not None:
            self._store.close()
        self._store = store
        self.setWindowTitle(f"Prospectra — {store.path.stem}")
        self.statusBar().showMessage(f"Project: {store.path}")
        logger.info("Opened project %s (schema v%s)", store.path, store.schema_version)

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "About Prospectra",
            f"<b>Prospectra {__version__}</b><br>Your data buddy.<br>"
            "Prep flows · statistical mining · dashboards · LLM explanations.",
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None
        super().closeEvent(event)
