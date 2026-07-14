# 2026-07-13 (P2): Flow workspace wired in — Save/Open Flow persist the canvas graph into the
# open .prospectra project (flows are versioned JSON docs in the project store).
# 2026-07-13 (P1): Main window now owns the Catalog session and wires the Sources dock to real
# work — open data files (CSV/Excel/JSON/Parquet), add databases by SQLAlchemy URL, browse tables,
# and land everything in the Data workspace (virtualized grid + profile cards).
# 2026-07-13 (P0): original shell — workspace tabs, docks, project-store File menu.

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMainWindow, QMessageBox

from prospectra import __version__
from prospectra.core.catalog import Catalog, Dataset, SqlConnection
from prospectra.core.connectors import SUPPORTED_FILE_SUFFIXES
from prospectra.core.flow import FlowError, FlowGraph
from prospectra.core.project import ProjectStore, ProjectStoreError
from prospectra.ui.data.data_tab import DataTab
from prospectra.ui.dialogs.add_database import AddDatabaseDialog
from prospectra.ui.docks.buddy import BuddyDock
from prospectra.ui.docks.log_view import LogDock, QtLogHandler
from prospectra.ui.docks.sources import SourcesDock
from prospectra.ui.flow.flow_tab import FlowTab
from prospectra.ui.tabs import make_central
from prospectra.ui.workers import run_in_pool

logger = logging.getLogger(__name__)

_FILE_FILTER = "Prospectra project (*.prospectra)"
_DATA_FILTER = (
    "Data files (" + " ".join(f"*{s}" for s in SUPPORTED_FILE_SUFFIXES) + ");;All files (*)"
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Prospectra")
        self.resize(1280, 800)
        self._store: ProjectStore | None = None
        self.catalog = Catalog()

        self._data_tab = DataTab(self.catalog)
        self._flow_tab = FlowTab()
        self._tabs = make_central({"Data": self._data_tab, "Flow": self._flow_tab})
        self.setCentralWidget(self._tabs)

        self._sources = SourcesDock()
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._sources)
        self._buddy = BuddyDock()
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._buddy)
        self._log = LogDock()
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log)
        # 2026-07-13 (P2): give the workspace the room — with default sizing the docks squeezed
        # the flow canvas into a strip (seen in a real-display screenshot). These are initial
        # sizes only; the user can still drag any splitter.
        self.resizeDocks([self._sources, self._buddy], [230, 280], Qt.Orientation.Horizontal)
        self.resizeDocks([self._log], [140], Qt.Orientation.Vertical)

        self._sources.open_file_requested.connect(self._open_data_file)
        self._sources.add_database_requested.connect(self._add_database)
        self._sources.dataset_activated.connect(self._show_dataset)
        self._sources.table_activated.connect(self._open_table)

        self._build_menus()
        self.statusBar().showMessage("Open a data file to get started — Sources ▸ Open File…")

    @property
    def log_handler(self) -> QtLogHandler:
        return self._log.handler

    # -- menus ---------------------------------------------------------------------

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        open_data = QAction("Open &Data File…", self)
        open_data.setShortcut("Ctrl+D")
        open_data.triggered.connect(self._open_data_file)
        file_menu.addAction(open_data)
        file_menu.addSeparator()
        new_action = QAction("&New Project…", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self._new_project)
        file_menu.addAction(new_action)
        open_action = QAction("&Open Project…", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._open_project)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        save_flow = QAction("&Save Flow to Project…", self)
        save_flow.setShortcut("Ctrl+S")
        save_flow.triggered.connect(self._save_flow)
        file_menu.addAction(save_flow)
        load_flow = QAction("Open &Flow from Project…", self)
        load_flow.triggered.connect(self._load_flow)
        file_menu.addAction(load_flow)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("&Help")
        about_action = QAction("&About Prospectra", self)
        about_action.triggered.connect(self._about)
        help_menu.addAction(about_action)

    # -- data sources -----------------------------------------------------------------

    def _open_data_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open data file", str(Path.home()), _DATA_FILTER
        )
        if not filename:
            return
        self.statusBar().showMessage(f"Opening {filename}…")
        run_in_pool(
            self.catalog.open_file,
            filename,
            on_result=self._datasets_opened,
            on_error=self._source_error,
        )

    def _datasets_opened(self, datasets: list[Dataset]) -> None:
        for ds in datasets:
            self._sources.add_dataset(ds)
        if datasets:
            self._show_dataset(datasets[0].id)
        self.statusBar().showMessage(f"Opened {len(datasets)} dataset(s)")

    def _add_database(self) -> None:
        dialog = AddDatabaseDialog(self)
        if not dialog.exec():
            return
        name, url = dialog.values()

        def connect() -> tuple[SqlConnection, list[str]]:
            conn = self.catalog.add_connection(name, url)
            return conn, self.catalog.list_tables(conn.id)

        self.statusBar().showMessage(f"Connecting to {name}…")
        run_in_pool(connect, on_result=self._connection_added, on_error=self._source_error)

    def _connection_added(self, pair: tuple[SqlConnection, list[str]]) -> None:
        connection, tables = pair
        self._sources.add_connection(connection, tables)
        self.statusBar().showMessage(f"Connected: {connection.name} ({len(tables)} tables)")

    def _open_table(self, connection_id: str, table: str) -> None:
        self.statusBar().showMessage(f"Loading table {table}…")
        run_in_pool(
            self.catalog.open_table,
            connection_id,
            table,
            on_result=self._table_opened,
            on_error=self._source_error,
        )

    def _table_opened(self, dataset: Dataset) -> None:
        self._sources.add_dataset(dataset)
        self._show_dataset(dataset.id)

    def _show_dataset(self, dataset_id: str) -> None:
        self._tabs.setCurrentWidget(self._data_tab)
        self._data_tab.show_dataset(dataset_id)

    def _source_error(self, message: str) -> None:
        self.statusBar().showMessage("Failed — see details")
        QMessageBox.warning(self, "Could not open source", message)

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

    # -- flows -----------------------------------------------------------------------

    def _save_flow(self) -> None:
        if self._store is None:
            QMessageBox.information(
                self, "No project open", "Create or open a project first (File ▸ New Project…)."
            )
            return
        name, ok = QInputDialog.getText(self, "Save flow", "Flow name:")
        if not ok or not name.strip():
            return
        record = self._store.save_flow(name.strip(), self._flow_tab.graph.to_doc())
        self.statusBar().showMessage(f"Saved flow '{record.name}' to {self._store.path.name}")
        logger.info("Saved flow %s (%s)", record.name, record.id)

    def _load_flow(self) -> None:
        if self._store is None:
            QMessageBox.information(self, "No project open", "Open a project first.")
            return
        flows = self._store.list_flows()
        if not flows:
            QMessageBox.information(self, "No flows", "This project has no saved flows yet.")
            return
        names = [f"{f.name}  ({f.updated_at})" for f in flows]
        choice, ok = QInputDialog.getItem(self, "Open flow", "Flow:", names, 0, False)
        if not ok:
            return
        record = flows[names.index(choice)]
        try:
            graph = FlowGraph.from_doc(record.doc)
        except FlowError as exc:
            QMessageBox.warning(self, "Could not open flow", str(exc))
            return
        self._flow_tab.load_graph(graph)
        self._tabs.setCurrentWidget(self._flow_tab)
        self.statusBar().showMessage(f"Opened flow '{record.name}'")

    def _attach(self, store: ProjectStore) -> None:
        if self._store is not None:
            self._store.close()
        self._store = store
        self.setWindowTitle(f"Prospectra — {store.path.stem}")
        self.statusBar().showMessage(f"Project: {store.path}")
        logger.info("Opened project %s (schema v%s)", store.path, store.schema_version)

    @property
    def project_store(self) -> ProjectStore | None:
        return self._store

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
        self.catalog.close()
        super().closeEvent(event)
