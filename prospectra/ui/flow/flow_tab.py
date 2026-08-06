# 2026-07-13 (P2): The Flow workspace, laid out like the sampleflow.png reference — node canvas on
# top; below it the selected node's profile cards + data preview; left rail holds the node palette,
# its params, and the changes list. Runs (preview/profile/output) go through the thread pool, so
# the canvas never freezes; failures are attributed to the node that caused them.

from __future__ import annotations

import logging
from functools import partial

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import prospectra.ui.mapping  # noqa: F401  (2026-07-31 P7: registers the mapping_doc editor)
from prospectra.core.flow import NODE_TYPES, FlowError, FlowGraph, FlowRunner
from prospectra.core.flow.runner import OutputResult, PreviewResult, SelectPreview
from prospectra.core.stats import TableProfile
from prospectra.ui.flow.canvas import FlowScene, FlowView
from prospectra.ui.flow.params_editor import ParamsEditor
from prospectra.ui.widgets.profile_cards import ProfileCardsPanel
from prospectra.ui.workers import run_in_pool

logger = logging.getLogger(__name__)

_CATEGORY_ORDER = ("input", "transform", "combine", "output")


class FlowTab(QWidget):
    dirty = Signal()  # the graph or its params changed (main window enables Save)

    def __init__(self) -> None:
        super().__init__()
        self.graph = FlowGraph()
        self._runner = FlowRunner()
        self._scene = FlowScene(self.graph)
        self._selected: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.addLayout(self._build_toolbar())

        columns = QSplitter(Qt.Orientation.Horizontal)
        columns.addWidget(self._build_left_rail())

        canvas_and_pane = QSplitter(Qt.Orientation.Vertical)
        self._view = FlowView(self._scene)
        canvas_and_pane.addWidget(self._view)
        canvas_and_pane.addWidget(self._build_bottom_pane())
        canvas_and_pane.setStretchFactor(0, 3)
        canvas_and_pane.setStretchFactor(1, 2)
        columns.addWidget(canvas_and_pane)
        columns.setStretchFactor(0, 0)
        columns.setStretchFactor(1, 1)
        columns.setSizes([240, 900])
        columns.setCollapsible(1, False)  # the canvas must never collapse to nothing
        root.addWidget(columns, 1)

        self._scene.selection_changed_id.connect(self._selection_changed)
        self._scene.node_double_clicked.connect(self._preview_node)
        self._scene.graph_changed.connect(self._graph_changed)
        self._scene.edge_rejected.connect(self._show_status)
        self._params.changed.connect(self._graph_changed)
        # 2026-07-14 (P5): drag a dataset from the Sources tree onto the canvas -> an Input node.
        self._view.dataset_dropped.connect(self._dataset_dropped)
        self._view.drop_rejected.connect(self._show_status)

    # -- construction -------------------------------------------------------------------

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self._node_picker = QComboBox()
        for category in _CATEGORY_ORDER:
            for type_name, cls in sorted(NODE_TYPES.items()):
                if cls.category == category:
                    self._node_picker.addItem(f"{category}: {cls.display_name}", type_name)
        add = QPushButton("Add node")
        add.clicked.connect(self._add_node)
        preview = QPushButton("Preview selected")
        preview.clicked.connect(lambda: self._preview_node(self._selected or ""))
        run = QPushButton("Run flow")
        run.clicked.connect(self._run_flow)
        self._run_button = run  # disabled while a run is in flight (see _run_flow)
        bar.addWidget(self._node_picker)
        bar.addWidget(add)
        bar.addSpacing(12)
        bar.addWidget(preview)
        bar.addWidget(run)
        bar.addStretch(1)
        self._status = QLabel("Add an Input node, then connect steps left to right.")
        self._status.setEnabled(False)
        bar.addWidget(self._status)
        return bar

    def _build_left_rail(self) -> QWidget:
        rail = QWidget()
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(0, 0, 0, 0)
        self._params = ParamsEditor()
        # 2026-07-31 (P7): custom param editors (the mapper) reach flow services through here.
        self._params.host = self
        layout.addWidget(self._params, 1)
        layout.addWidget(QLabel("Changes"))
        self._changes = QListWidget()
        self._changes.setMaximumHeight(180)
        layout.addWidget(self._changes)
        return rail

    def _build_bottom_pane(self) -> QWidget:
        pane = QTabWidget()
        pane.setDocumentMode(True)
        self._cards = ProfileCardsPanel()
        pane.addTab(self._cards, "Profile")
        self._preview_table = QTableWidget()
        self._preview_table.setAlternatingRowColors(True)
        pane.addTab(self._preview_table, "Data preview")
        return pane

    # -- graph events ---------------------------------------------------------------------

    def _add_node(self) -> None:
        type_name = self._node_picker.currentData()
        # Stagger new nodes so they don't stack on one another.
        count = len(self.graph.nodes)
        pos = self._view.mapToScene(40 + 30 * (count % 5), 40 + 70 * (count % 4))
        node_id = self._scene.add_node(type_name, pos)
        self._scene.clearSelection()
        item = self._scene._nodes[node_id]
        item.setSelected(True)

    def _dataset_dropped(self, dataset: str, origin: str, x: float, y: float) -> None:
        """A dataset dropped on the canvas becomes an Input node pointed at its file."""
        node_id = self._scene.add_node("input_file", QPointF(x, y))
        self.graph.nodes[node_id].node.params["path"] = origin
        self._scene.clearSelection()
        self._scene._nodes[node_id].setSelected(True)
        self._graph_changed()
        self._show_status(f"Added “{dataset}” as an Input node — connect a step to it.")

    def _graph_changed(self) -> None:
        # 2026-08-05: the runner's schema cache is keyed on compiled SQL, which cannot see a
        # source FILE changing underneath it. Clearing on every graph edit keeps the mapper's
        # draggable column list from serving a stale schema for the rest of the session.
        self._runner.clear_caches()
        self._refresh_changes()
        self._scene.refresh_edges()
        for item in self._scene._nodes.values():
            item.update()  # subtitles/badges follow param edits
        self.dirty.emit()

    def _selection_changed(self, node_id: str) -> None:
        self._selected = node_id or None
        instance = self.graph.nodes.get(node_id) if node_id else None
        self._params.set_node(instance)

    def _refresh_changes(self) -> None:
        """The changes list: every step in run order, like Tableau Prep's Changes pane."""
        self._changes.clear()
        try:
            order = self.graph.topo_order()
        except FlowError:
            return
        for node_id in order:
            instance = self.graph.nodes[node_id]
            node = instance.node
            detail = ", ".join(f"{k}={v}" for k, v in node.params.items() if str(v).strip())
            label = type(node).display_name
            self._changes.addItem(f"{label}: {detail}" if detail else label)

    # -- running ----------------------------------------------------------------------------

    def _preview_node(self, node_id: str) -> None:
        if not node_id:
            self._show_status("Select a node first.")
            return
        self._show_status("Previewing…")
        self._scene.mark_error(None, None)
        run_in_pool(
            self._runner.preview,
            self.graph,
            node_id,
            on_result=self._preview_ready,
            on_error=partial(self._node_failed, node_id),
        )
        run_in_pool(
            self._runner.profile,
            self.graph,
            node_id,
            on_result=self._profile_ready,
            on_error=partial(self._node_failed, node_id),
        )

    def _preview_ready(self, result: PreviewResult) -> None:
        self._preview_table.clear()
        self._preview_table.setColumnCount(len(result.columns))
        self._preview_table.setRowCount(len(result.rows))
        self._preview_table.setHorizontalHeaderLabels(
            [f"{name}\n{dtype}" for name, dtype in result.columns]
        )
        for r, row in enumerate(result.rows):
            for c, value in enumerate(row):
                self._preview_table.setItem(
                    r, c, QTableWidgetItem("" if value is None else str(value))
                )
        shown = min(len(result.rows), result.total_rows)
        self._show_status(f"{result.total_rows:,} rows · showing first {shown:,}")

    def _profile_ready(self, profile: TableProfile) -> None:
        self._cards.set_profile(profile)

    def _run_flow(self) -> None:
        if not self.graph.output_nodes():
            self._show_status("Add an Output node to run the flow.")
            return
        # 2026-08-05: one run at a time. The button stayed live during a run, so double-clicking a
        # graph with a REST-write node could start two concurrent live write jobs against the same
        # API — and the worker reads self.graph while the canvas is still editable.
        if not self._run_button.isEnabled():
            return
        self._run_button.setEnabled(False)
        # 2026-07-31 (P7): a flow containing a live write NEVER runs from one click. The first
        # press is a dry run; going live takes a typed confirmation naming what will happen.
        destructive = [
            nid for nid in self.graph.output_nodes() if self.graph.nodes[nid].node.destructive
        ]
        if destructive:
            self._run_destructive(destructive)
            return
        self._show_status("Running…")
        self._scene.mark_error(None, None)
        run_in_pool(
            self._runner.run,
            self.graph,
            on_result=self._run_done,
            on_error=self._run_failed,
            on_finished=self._run_finished,
        )

    def _run_destructive(self, destructive: list[str]) -> None:
        names = ", ".join(self.graph.nodes[nid].node.display_name for nid in destructive)
        self._show_status(f"Dry run first — {names} sends live writes…")
        self._scene.mark_error(None, None)
        run_in_pool(
            lambda: self._runner.run(self.graph, dry_run=True),
            on_result=self._dry_run_done,
            on_error=self._run_failed,
            on_finished=self._run_finished,
        )

    def _dry_run_done(self, results: list[OutputResult]) -> None:
        self._run_done(results)
        total = sum(r.attempted for r in results if r.dry_run)
        from PySide6.QtWidgets import QInputDialog

        typed, ok = QInputDialog.getText(
            self,
            "Send live writes?",
            f"The dry run rehearsed {total:,} row(s). This will now send REAL requests to an\n"
            "external system — a wrong mapping there is not undoable from here.\n\n"
            "Type WRITE to send, or cancel to stop after the rehearsal:",
        )
        if not ok or typed.strip() != "WRITE":
            self._show_status("Stopped after the dry run — nothing was sent.")
            return
        self._show_status("Sending live writes…")
        self._run_button.setEnabled(False)  # the dry run's on_finished re-enabled it
        run_in_pool(
            lambda: self._runner.run(self.graph, allow_writes=True),
            on_result=self._run_done,
            on_error=self._run_failed,
            on_finished=self._run_finished,
        )

    def _run_finished(self) -> None:
        self._run_button.setEnabled(True)

    def _run_done(self, results: list[OutputResult]) -> None:
        parts = []
        for r in results:
            if r.dry_run:
                parts.append(f"dry run: {r.attempted:,} row(s) rehearsed")
            elif r.path:
                parts.append(f"{r.path} ({r.rows:,} rows)")
            else:
                parts.append(f"{r.written:,} written, {r.failed:,} failed")
        summary = ", ".join(parts)
        # 2026-07-31 (P7): notes reach the user, never just a logger (the project's own rule).
        notes = [note for r in results for note in r.notes]
        if notes:
            summary += "  ·  " + " · ".join(notes)
        self._show_status(summary)
        logger.info("Flow run complete: %s", summary)

    def _run_failed(self, message: str) -> None:
        self._show_status("Run failed")
        QMessageBox.warning(self, "Flow run failed", message)

    def _node_failed(self, node_id: str, message: str) -> None:
        self._scene.mark_error(node_id, message)  # red border on the offending node
        self._show_status(f"Error: {message}")

    def _show_status(self, message: str) -> None:
        self._status.setText(message)

    # -- services for custom param editors (2026-07-31 P7) ---------------------------------

    def upstream_columns_for(self, node_id: str) -> list[tuple[str, str]]:
        """The columns arriving at a node's first input — what the mapper drags from."""
        inputs = self.graph.inputs_of(node_id)
        if not inputs:
            return []
        return self._runner.columns(self.graph, inputs[0])

    def preview_select_for(self, node_id: str, select_sql: str, limit: int = 20) -> SelectPreview:
        """An ad-hoc SELECT over a node's first input (relation name `upstream`)."""
        inputs = self.graph.inputs_of(node_id)
        if not inputs:
            raise FlowError("connect an input first")
        return self._runner.preview_select(self.graph, inputs[0], select_sql, limit=limit)

    # -- persistence ------------------------------------------------------------------------

    def load_graph(self, graph: FlowGraph) -> None:
        self.graph = graph
        self._scene.graph = graph
        self._scene.rebuild()
        self._selected = None
        self._params.set_node(None)
        self._refresh_changes()
