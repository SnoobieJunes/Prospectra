# 2026-07-14 (P5): Dashboards workspace wired in (saved into the project like flows), the scraper
# reachable from Sources, and the drag-and-drop backbone closed: dropping columns on "New dataset"
# derives the dataset AND writes the flow that produces it onto the canvas.
# 2026-07-14 (P4): Data Buddy dock wired in — it owns its own query sandbox, follows the catalog,
# and receives each scan's findings so it can discuss them. Settings (provider, key, privacy) live
# behind File ▸ Data Buddy Settings.
# 2026-07-13 (P3): Analyze workspace wired in — its dataset list follows the catalog, and
# findings can be saved into the open project (with their sample seed, so they reproduce).
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
from prospectra.core.connectors.dialects import redact_url
from prospectra.core.connectors.rest import RestMapping
from prospectra.core.flow import FlowError, FlowGraph, flow_from_columns, flow_readable
from prospectra.core.http import HttpRequest
from prospectra.core.llm import secrets as secret_store
from prospectra.core.mining import save_scan
from prospectra.core.project import ProjectStore, ProjectStoreError
from prospectra.core.scraper import ScrapeResult, scrape
from prospectra.core.viz import Dashboard
from prospectra.ui.analysis.analyze_tab import AnalyzeTab
from prospectra.ui.api.playground import ApiPlaygroundTab
from prospectra.ui.dashboards.dashboard_tab import DashboardTab
from prospectra.ui.data.data_tab import DataTab
from prospectra.ui.dialogs.add_api import AddApiDialog
from prospectra.ui.dialogs.add_database import AddDatabaseDialog
from prospectra.ui.dialogs.scrape import ScrapeDialog
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
        self._analyze_tab = AnalyzeTab(self.catalog)
        self._dashboard_tab = DashboardTab(self.catalog)
        self._api_tab = ApiPlaygroundTab()  # 2026-07-31 (P7)
        self._tabs = make_central(
            {
                "Data": self._data_tab,
                "Flow": self._flow_tab,
                "Analyze": self._analyze_tab,
                "Dashboards": self._dashboard_tab,
                "API": self._api_tab,
            }
        )
        self.setCentralWidget(self._tabs)
        self._saved_apis: dict[str, RestMapping] = {}  # connection record id -> mapping
        self._api_tab.request_save_requested.connect(self._save_api_request)
        self._api_tab.source_save_requested.connect(self._save_api_source)

        self._sources = SourcesDock()
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._sources)
        self._buddy = BuddyDock(self.catalog)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._buddy)
        self._analyze_tab.scan_finished.connect(self._buddy.set_findings)
        self._log = LogDock()
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log)
        # 2026-07-13 (P2): give the workspace the room — with default sizing the docks squeezed
        # the flow canvas into a strip (seen in a real-display screenshot). These are initial
        # sizes only; the user can still drag any splitter.
        self.resizeDocks([self._sources, self._buddy], [230, 280], Qt.Orientation.Horizontal)
        self.resizeDocks([self._log], [140], Qt.Orientation.Vertical)

        self._sources.open_file_requested.connect(self._open_data_file)
        self._sources.add_database_requested.connect(self._add_database)
        self._sources.add_api_requested.connect(self._add_api)
        self._sources.scrape_requested.connect(self._scrape_web)
        self._sources.new_dataset_requested.connect(self._new_dataset_from_columns)
        self._sources.dataset_activated.connect(self._show_dataset)
        self._sources.table_activated.connect(self._open_table)
        self._sources.api_activated.connect(self._open_saved_api)

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
        save_findings = QAction("Save F&indings to Project", self)
        save_findings.triggered.connect(self._save_findings)
        file_menu.addAction(save_findings)
        save_dashboard = QAction("Save Dash&board to Project…", self)
        save_dashboard.triggered.connect(self._save_dashboard)
        file_menu.addAction(save_dashboard)
        load_dashboard = QAction("Open Dashboar&d from Project…", self)
        load_dashboard.triggered.connect(self._load_dashboard)
        file_menu.addAction(load_dashboard)
        file_menu.addSeparator()
        scrape_action = QAction("Scrape &Web Page…", self)
        scrape_action.triggered.connect(self._scrape_web)
        file_menu.addAction(scrape_action)
        file_menu.addSeparator()
        buddy_settings = QAction("Data &Buddy Settings…", self)
        buddy_settings.triggered.connect(self._buddy.open_settings)
        file_menu.addAction(buddy_settings)
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
        self._analyze_tab.refresh_datasets()
        self.statusBar().showMessage(f"Opened {len(datasets)} dataset(s)")

    def _add_database(self) -> None:
        dialog = AddDatabaseDialog(self)
        if not dialog.exec():
            return
        name, url = dialog.values()

        # 2026-07-14 (P6): the password goes to the OS keychain and the project file keeps a URL
        # with the credential redacted — a .prospectra file must never be a password leak.
        secret = dialog.secret()
        if secret and self._store is not None:
            ref = f"db:{name}"
            try:
                secret_store.set_api_key(ref, secret)
            except secret_store.SecretsError as exc:
                logger.warning("Keychain unavailable; the password is not saved: %s", exc)
                ref = ""
            self._store.save_connection(name, "sqlalchemy", {"url": redact_url(url)}, ref or None)
        elif self._store is not None:
            self._store.save_connection(name, "sqlalchemy", {"url": redact_url(url)}, None)

        def connect() -> tuple[SqlConnection, list[str]]:
            conn = self.catalog.add_connection(name, url)
            return conn, self.catalog.list_tables(conn.id)

        self.statusBar().showMessage(f"Connecting to {name}…")
        run_in_pool(connect, on_result=self._connection_added, on_error=self._source_error)

    def _connection_added(self, pair: tuple[SqlConnection, list[str]]) -> None:
        connection, tables = pair
        self._sources.add_connection(connection, tables)
        self.statusBar().showMessage(f"Connected: {connection.name} ({len(tables)} tables)")

    # -- APIs (P6) --------------------------------------------------------------------

    def _add_api(self) -> None:
        dialog = AddApiDialog(self)
        if not dialog.exec():
            return
        mapping = dialog.mapping()
        token = dialog.token()
        if token and mapping.auth.kind != "none":
            # The credential goes to the OS keychain; the mapping saved into the project holds only
            # the *reference* to it, so the project file is safe to share.
            try:
                secret_store.set_api_key(mapping.auth.secret_ref, token)
            except secret_store.SecretsError as exc:
                logger.warning("Keychain unavailable; the token is used this session only: %s", exc)
        if self._store is not None:
            self._store.save_connection(
                mapping.name, "rest", mapping.to_dict(), mapping.auth.secret_ref or None
            )
            self._restore_saved_connections(self._store)  # 2026-07-31 (P7): show it immediately

        self.statusBar().showMessage(f"Fetching {mapping.url}…")
        run_in_pool(
            self.catalog.open_api,
            mapping,
            token or None,
            on_result=self._api_opened,
            on_error=self._source_error,
        )

    def _api_opened(self, dataset: Dataset) -> None:
        self._datasets_opened([dataset])
        self.statusBar().showMessage(f"Opened {dataset.name} — {dataset.origin}")

    # -- the API playground (P7) ------------------------------------------------------

    def _save_api_request(self, request: HttpRequest) -> None:
        """Persist a playground request into the project (connector_type "http_request")."""
        if self._store is None:
            QMessageBox.information(
                self, "No project open", "Create or open a project first (File ▸ New Project…)."
            )
            return
        name, ok = QInputDialog.getText(self, "Save request", "Request name:")
        if not ok or not name.strip():
            return
        record = self._store.save_connection(name.strip(), "http_request", request.to_dict())
        self._restore_saved_connections(self._store)
        self.statusBar().showMessage(f"Saved request '{record.name}' to {self._store.path.name}")

    def _save_api_source(self, mapping: RestMapping, token: str) -> None:
        """Promote a playground request to a data source — the same path "Add API…" takes."""
        name, ok = QInputDialog.getText(
            self, "Save as data source", "Table name:", text=mapping.name
        )
        if not ok or not name.strip():
            return
        mapping.name = name.strip()
        # 2026-08-05: say so before doing anything. Without a project this used to write the token
        # to the keychain, persist NO record, show "Fetching…", and let the user believe the source
        # was saved — it died with the session.
        if self._store is None:
            proceed = QMessageBox.question(
                self,
                "No project open",
                f"There is no project open, so “{mapping.name}” cannot be saved.\n\n"
                "Fetch it once for this session anyway? (Create a project first if you want to "
                "keep it.)",
            )
            if proceed != QMessageBox.StandardButton.Yes:
                return
        if mapping.auth.kind != "none" and not mapping.auth.secret_ref:
            mapping.auth.secret_ref = f"api:{mapping.name}"
        if token and mapping.auth.kind != "none":
            try:
                secret_store.set_api_key(mapping.auth.secret_ref, token)
            except secret_store.SecretsError as exc:
                logger.warning("Keychain unavailable; the token is used this session only: %s", exc)
        if self._store is not None:
            record = self._store.save_connection(
                mapping.name, "rest", mapping.to_dict(), mapping.auth.secret_ref or None
            )
            self._saved_apis[record.id] = mapping
            self._sources.add_saved_api(record.id, mapping.name, mapping.url)
        self.statusBar().showMessage(f"Fetching {mapping.url}…")
        run_in_pool(
            self.catalog.open_api,
            mapping,
            token or None,
            on_result=self._api_opened,
            on_error=self._source_error,
        )

    def _open_saved_api(self, record_id: str) -> None:
        """Double-click on a saved API source: re-fetch it (explicitly — never behind the back)."""
        mapping = self._saved_apis.get(record_id)
        if mapping is None:
            return

        def fetch() -> Dataset:
            secret = None
            if mapping.auth.kind != "none" and mapping.auth.secret_ref:
                secret = secret_store.get_api_key(mapping.auth.secret_ref)
                if not secret:
                    raise RuntimeError(
                        f"The credential {mapping.auth.secret_ref!r} is not in this machine's "
                        "keychain. Re-enter the token via Sources ▸ Add API…"
                    )
            return self.catalog.open_api(mapping, secret)

        self.statusBar().showMessage(f"Fetching {mapping.url}…")
        run_in_pool(fetch, on_result=self._api_opened, on_error=self._source_error)

    def _restore_saved_connections(self, store: ProjectStore) -> None:
        """Bring the project's saved API sources and playground requests back into the UI.

        Before P7, `list_connections()` had exactly one caller (a test) — everything saved into
        the connections table was write-only, and saved API sources never came back.
        """
        self._saved_apis.clear()
        self._sources.clear_saved_apis()
        saved_requests: list[tuple[str, str, HttpRequest]] = []
        try:
            # 2026-08-05: list_connections() json.loads()es every row BEFORE the per-row guard
            # below could ever run, so one corrupt row raised straight out of project open. The
            # comment claiming otherwise was wrong.
            records = store.list_connections()
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("Could not read this project's saved connections: %s", exc)
            self._api_tab.set_saved_requests([])
            self.statusBar().showMessage(
                "This project's saved connections could not be read — everything else opened."
            )
            return
        for record in records:
            try:
                if record.connector_type == "rest":
                    mapping = RestMapping.from_dict(record.config)
                    self._saved_apis[record.id] = mapping
                    self._sources.add_saved_api(record.id, record.name, mapping.url)
                elif record.connector_type == "http_request":
                    saved_requests.append(
                        (record.id, record.name, HttpRequest.from_dict(record.config))
                    )
            except (ValueError, KeyError) as exc:
                # A newer build's row (or a corrupt one) must not sink the whole project open.
                logger.warning("Skipping saved connection %r: %s", record.name, exc)
        self._api_tab.set_saved_requests(saved_requests)

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
        self._analyze_tab.refresh_datasets()

    def _show_dataset(self, dataset_id: str) -> None:
        self._tabs.setCurrentWidget(self._data_tab)
        self._data_tab.show_dataset(dataset_id)

    def _source_error(self, message: str) -> None:
        self.statusBar().showMessage("Failed — see details")
        QMessageBox.warning(self, "Could not open source", message)

    # -- scraping (P5) ------------------------------------------------------------------

    @property
    def staging_dir(self) -> Path:
        """Where scraped tables land: beside the project, or in the working folder without one."""
        if self._store is not None:
            return self._store.staging_dir
        fallback = Path.cwd() / "prospectra_scraped"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    def _scrape_web(self) -> None:
        staging = self.staging_dir
        dialog = ScrapeDialog(staging, self)
        if not dialog.exec():
            return
        url, tables_only, max_tables = dialog.values()
        if not url:
            return
        self.statusBar().showMessage(f"Fetching {url}… (robots.txt is checked first)")
        run_in_pool(
            scrape,
            url,
            staging,
            tables_only=tables_only,
            max_tables=max_tables,
            on_result=self._scrape_done,
            on_error=self._scrape_failed,
        )

    def _scrape_done(self, result: ScrapeResult) -> None:
        # Each scraped table is now an ordinary CSV — so it opens through the ordinary file path.
        opened: list[Dataset] = []
        for emitted in result.files:
            try:
                opened.extend(self.catalog.open_file(emitted.path))
            except Exception as exc:  # one bad table must not sink the rest
                logger.warning("Could not open scraped file %s: %s", emitted.path, exc)
        if opened:
            self._datasets_opened(opened)
            self.statusBar().showMessage(
                f"Scraped {len(opened)} table(s) from {result.final_url} into {self.staging_dir}"
            )
            return
        if result.article_path is not None:
            QMessageBox.information(
                self,
                "No tables on that page",
                f"Saved the page's text to {result.article_path}.\n\nThere were no data tables to "
                "extract.",
            )
            return
        self.statusBar().showMessage(result.summary)

    def _scrape_failed(self, message: str) -> None:
        self.statusBar().showMessage("Scrape failed — see details")
        QMessageBox.warning(self, "Could not scrape that page", message)

    # -- derived datasets (P5 drag-and-drop backbone) --------------------------------------

    def _new_dataset_from_columns(self, source_id: str, columns: list[str]) -> None:
        """Columns dropped on "New dataset": derive the dataset AND write the flow that builds it.

        The flow is the point. A hidden SELECT would give the same table with no provenance; a
        generated flow lands on the canvas where it can be seen, edited, re-run and saved.
        """
        source = self.catalog.datasets.get(source_id)
        if source is None or not columns:
            return
        name = f"{source.name} ({len(columns)} col{'s' if len(columns) > 1 else ''})"
        try:
            dataset = self.catalog.derive_dataset(source_id, list(columns), name)
        except (ValueError, KeyError) as exc:
            QMessageBox.warning(self, "Could not derive dataset", str(exc))
            return
        self._sources.add_dataset(dataset)
        self._analyze_tab.refresh_datasets()
        self._show_dataset(dataset.id)

        if not flow_readable(source.origin):
            # Excel sheets and database tables cannot be an Input node yet (a P2 limitation kept
            # honest in Deviations.md) — the dataset is real, the generated flow is not possible.
            self.statusBar().showMessage(
                f"Created “{name}”. No flow was generated: flows can only read files DuckDB opens "
                f"natively, and this dataset comes from {source.origin}."
            )
            return
        out_path = self.staging_dir / f"{dataset.view_name}_{len(columns)}cols.csv"
        graph = flow_from_columns(source.origin, list(columns), out_path)
        self._flow_tab.load_graph(graph)
        self.statusBar().showMessage(
            f"Created “{name}” and generated the flow that builds it (see the Flow tab)."
        )

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

    def _save_findings(self) -> None:
        if self._store is None:
            QMessageBox.information(self, "No project open", "Create or open a project first.")
            return
        scan = self._analyze_tab._scan
        if scan is None:
            QMessageBox.information(self, "No findings", "Run a scan on the Analyze tab first.")
            return
        count = save_scan(self._store, scan)
        self.statusBar().showMessage(
            f"Saved {count} finding(s) to {self._store.path.name} (seed {scan.seed})"
        )

    # -- dashboards (P5) -------------------------------------------------------------------

    def _save_dashboard(self) -> None:
        if self._store is None:
            QMessageBox.information(
                self, "No project open", "Create or open a project first (File ▸ New Project…)."
            )
            return
        dashboard = self._dashboard_tab.dashboard
        if not dashboard.tiles:
            QMessageBox.information(
                self, "Empty dashboard", "Add at least one chart on the Dashboards tab first."
            )
            return
        name, ok = QInputDialog.getText(self, "Save dashboard", "Name:", text=dashboard.name)
        if not ok or not name.strip():
            return
        dashboard.name = name.strip()
        # Saved by id: re-saving the open dashboard updates it instead of making a copy.
        record = self._store.save_dashboard(dashboard.name, dashboard.to_doc(), dashboard.id)
        self.statusBar().showMessage(
            f"Saved dashboard '{record.name}' ({len(dashboard.tiles)} chart(s)) to "
            f"{self._store.path.name}"
        )

    def _load_dashboard(self) -> None:
        if self._store is None:
            QMessageBox.information(self, "No project open", "Open a project first.")
            return
        records = self._store.list_dashboards()
        if not records:
            QMessageBox.information(
                self, "No dashboards", "This project has no saved dashboards yet."
            )
            return
        names = [f"{r.name}  ({r.updated_at})" for r in records]
        choice, ok = QInputDialog.getItem(self, "Open dashboard", "Dashboard:", names, 0, False)
        if not ok:
            return
        record = records[names.index(choice)]
        try:
            dashboard = Dashboard.from_doc(record.layout)
        except ValueError as exc:
            QMessageBox.warning(self, "Could not open dashboard", str(exc))
            return
        self._dashboard_tab.load_dashboard(dashboard)
        self._tabs.setCurrentWidget(self._dashboard_tab)

    def _attach(self, store: ProjectStore) -> None:
        if self._store is not None:
            self._store.close()
        self._store = store
        self.setWindowTitle(f"Prospectra — {store.path.stem}")
        self.statusBar().showMessage(f"Project: {store.path}")
        # 2026-07-31 (P7): saved API sources and playground requests come back on open.
        self._restore_saved_connections(store)
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
        self._buddy.shutdown()  # closes the assistant's query sandbox
        self.catalog.close()
        super().closeEvent(event)
