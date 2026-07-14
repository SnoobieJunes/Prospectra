# 2026-07-14 (P5): The Dashboards workspace — build a chart by dropping columns on shelves, add it
# to a grid of tiles, save the grid into the project.
#
# The builder is deliberately opinionated about what it will let you ask for: the mark list is
# filtered by what is actually on the shelves (no histogram of a text column, no scatter without
# two numeric columns), so an impossible chart is unreachable rather than merely an error message.
# Every query runs on the thread pool — a bar chart over a 10M-row table must not freeze the GUI.

from __future__ import annotations

import logging
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from prospectra.core.catalog import Catalog
from prospectra.core.viz import AGGREGATIONS, ChartData, ChartSpec, Dashboard, fetch_chart_data
from prospectra.ui.dashboards.chart_tile import ChartTile
from prospectra.ui.dashboards.shelf import ColumnShelf
from prospectra.ui.workers import run_in_pool

logger = logging.getLogger(__name__)

_MARK_LABELS = {
    "bar": "Bar — compare amounts across categories",
    "line": "Line — a value across an ordered x",
    "scatter": "Scatter — relationship between two numbers",
    "box": "Box — distribution of a number across groups",
    "histogram": "Histogram — the shape of one number",
}


class DashboardTab(QWidget):
    """Chart builder (left) + the dashboard's tiles (right)."""

    def __init__(self, catalog: Catalog) -> None:
        super().__init__()
        self._catalog = catalog
        self.dashboard = Dashboard()
        self._tiles: dict[str, ChartTile] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.addLayout(self._build_toolbar())

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._build_builder())
        split.addWidget(self._build_grid())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([320, 860])
        split.setCollapsible(1, False)
        root.addWidget(split, 1)
        self._refresh_marks()

    # -- construction ---------------------------------------------------------------------------

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self._name = QLineEdit(self.dashboard.name)
        self._name.setMaximumWidth(240)
        self._name.textChanged.connect(self._rename)
        bar.addWidget(QLabel("Dashboard"))
        bar.addWidget(self._name)
        refresh = QPushButton("Refresh all")
        refresh.clicked.connect(self.refresh_tiles)
        bar.addWidget(refresh)
        bar.addStretch(1)
        self._status = QLabel(
            "Drag a column from the Data grid onto a shelf, then Add to dashboard."
        )
        self._status.setEnabled(False)
        bar.addWidget(self._status)
        return bar

    def _build_builder(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 6, 0)

        layout.addWidget(QLabel("<b>New chart</b>"))
        self._x = ColumnShelf("X", "drop a column (the grouping)")
        self._y = ColumnShelf("Y", "drop a numeric column (the value)")
        self._color = ColumnShelf("Colour", "optional: split into series")
        for shelf in (self._x, self._y, self._color):
            shelf.changed.connect(self._shelves_changed)
            layout.addWidget(shelf)

        form = QHBoxLayout()
        self._mark = QComboBox()
        self._mark.currentIndexChanged.connect(self._preview)
        form.addWidget(QLabel("Chart"))
        form.addWidget(self._mark, 1)
        layout.addLayout(form)

        agg_row = QHBoxLayout()
        self._agg = QComboBox()
        for name in AGGREGATIONS:
            self._agg.addItem(name, name)
        self._agg.setCurrentText("sum")
        self._agg.currentIndexChanged.connect(self._preview)
        agg_row.addWidget(QLabel("Summarize"))
        agg_row.addWidget(self._agg, 1)
        layout.addLayout(agg_row)

        scales = QHBoxLayout()
        self._log_x = QCheckBox("log X")
        self._log_y = QCheckBox("log Y")
        for box in (self._log_x, self._log_y):
            box.setToolTip(
                "A log scale cannot show zero or negative values — any it has to drop are counted "
                "and reported under the chart."
            )
            box.stateChanged.connect(self._preview)
            scales.addWidget(box)
        scales.addStretch(1)
        layout.addLayout(scales)

        self._add = QPushButton("Add to dashboard")
        self._add.setEnabled(False)
        self._add.clicked.connect(self._add_tile)
        layout.addWidget(self._add)
        self._builder_status = QLabel("Drop a column on X to start.")
        self._builder_status.setWordWrap(True)
        self._builder_status.setEnabled(False)
        layout.addWidget(self._builder_status)
        layout.addStretch(1)
        return panel

    def _build_grid(self) -> QWidget:
        area = QScrollArea()
        area.setWidgetResizable(True)
        holder = QWidget()
        self._grid = QGridLayout(holder)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._empty = QLabel(
            "This dashboard is empty.\n\nBuild a chart on the left — drag a column from the Data "
            "grid onto the X shelf — then Add to dashboard."
        )
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setEnabled(False)
        self._grid.addWidget(self._empty, 0, 0)
        area.setWidget(holder)
        return area

    # -- builder state ---------------------------------------------------------------------------

    def _dataset_id(self) -> str:
        """The dataset the chart reads. Shelves must agree — a chart cannot span two datasets."""
        return self._x.dataset_id or self._y.dataset_id

    def _available_marks(self) -> list[str]:
        """Only the marks the dropped columns can actually support."""
        if not self._x.column:
            return []
        marks = []
        if self._x.numeric:
            marks.append("histogram")
        if self._y.numeric:
            marks.extend(["bar", "line", "box"])
            if self._x.numeric:
                marks.append("scatter")
        elif not self._y.column:
            marks.append("bar")  # count of rows per category needs no Y
        return marks

    def _refresh_marks(self) -> None:
        current = self._mark.currentData()
        marks = self._available_marks()
        self._mark.blockSignals(True)
        self._mark.clear()
        for mark in marks:
            self._mark.addItem(_MARK_LABELS[mark], mark)
        if current in marks:
            self._mark.setCurrentIndex(marks.index(current))
        self._mark.blockSignals(False)
        self._mark.setEnabled(bool(marks))
        self._agg.setEnabled(self._mark.currentData() in ("bar", "line"))

    def _shelves_changed(self, *_args: object) -> None:
        ids = {s.dataset_id for s in (self._x, self._y, self._color) if s.dataset_id}
        if len(ids) > 1:
            # Two datasets on one chart would need a join; the flow canvas is where joins live.
            self._builder_status.setText(
                "Those columns come from different datasets. Join them in a Flow first, then "
                "chart the result."
            )
            self._add.setEnabled(False)
            return
        self._refresh_marks()
        self._preview()

    def current_spec(self) -> ChartSpec | None:
        dataset_id = self._dataset_id()
        mark = self._mark.currentData()
        if not dataset_id or not mark:
            return None
        dataset = self._catalog.datasets.get(dataset_id)
        if dataset is None:
            return None
        spec = ChartSpec(
            mark=str(mark),
            x=self._x.column,
            y=self._y.column,
            color=self._color.column,
            agg=str(self._agg.currentData() or "sum"),
            x_scale="log" if self._log_x.isChecked() else "linear",
            y_scale="log" if self._log_y.isChecked() else "linear",
            dataset=dataset.name,
            origin=dataset.origin,
        )
        try:
            spec.validate()
        except ValueError:
            return None
        return spec

    def _preview(self, *_args: object) -> None:
        self._agg.setEnabled(self._mark.currentData() in ("bar", "line"))
        spec = self.current_spec()
        if spec is None:
            self._add.setEnabled(False)
            self._builder_status.setText(
                "Drop a column on X to start."
                if not self._x.column
                else "Drop a numeric column on Y (or leave Y empty and pick Bar to count rows)."
            )
            return
        self._add.setEnabled(True)
        self._builder_status.setText(f"Ready: {spec.display_title}")

    # -- tiles ------------------------------------------------------------------------------------

    def _add_tile(self) -> None:
        spec = self.current_spec()
        if spec is None:
            return
        self.dashboard.add(spec)
        self._rebuild_grid()
        self._load_tile(spec)
        self._status.setText(f"Added “{spec.display_title}”")

    def _remove_tile(self, spec_id: str) -> None:
        self.dashboard.remove(spec_id)
        self._rebuild_grid()

    def _rebuild_grid(self) -> None:
        """Re-lay the grid, REUSING the widget of every tile that is still on the dashboard.

        Recreating them all was a real bug, caught by looking at a screenshot rather than by any
        test: adding a second chart blanked the first. Its data was still in flight on the thread
        pool, and the callback delivered it to the widget that had just been thrown away, so the
        replacement widget sat empty forever. A tile's widget now outlives its neighbours' arrival.
        """
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None and widget is not self._empty:
                widget.setParent(None)  # unparented, not destroyed — self._tiles still holds it

        live = {tile.spec.id for tile in self.dashboard.tiles}
        for spec_id in [sid for sid in self._tiles if sid not in live]:
            self._tiles.pop(spec_id).deleteLater()

        if not self.dashboard.tiles:
            self._grid.addWidget(self._empty, 0, 0)
            self._empty.setVisible(True)
            return

        self._empty.setVisible(False)
        for tile in self.dashboard.tiles:
            widget = self._tiles.get(tile.spec.id)
            if widget is None:
                widget = ChartTile(tile.spec)
                widget.remove_requested.connect(self._remove_tile)
                self._tiles[tile.spec.id] = widget
            self._grid.addWidget(widget, tile.row, tile.column)
            widget.setVisible(True)

    def _resolve(self, spec: ChartSpec) -> str | None:
        """The view name this spec's dataset maps to right now, or None when it isn't open."""
        for dataset in self._catalog.datasets.values():
            if dataset.name == spec.dataset:
                return dataset.view_name
        return None

    def _load_tile(self, spec: ChartSpec) -> None:
        widget = self._tiles.get(spec.id)
        if widget is None:
            return
        view = self._resolve(spec)
        if view is None:
            widget.set_unavailable(
                f"“{spec.dataset}” is not open. Open {spec.origin or 'it'} "
                "(Sources ▸ Open File…) and press Refresh all."
            )
            return

        def work() -> ChartData:
            return fetch_chart_data(self._catalog.cursor(), spec, view)

        run_in_pool(
            work,
            on_result=widget.set_data,
            on_error=partial(self._tile_failed, spec.id),
        )

    def _tile_failed(self, spec_id: str, message: str) -> None:
        widget = self._tiles.get(spec_id)
        if widget is not None:
            widget.set_unavailable(f"Could not draw this chart: {message}")
        logger.error("Chart tile %s failed: %s", spec_id, message)

    def refresh_tiles(self) -> None:
        for tile in self.dashboard.tiles:
            self._load_tile(tile.spec)

    def _rename(self, text: str) -> None:
        self.dashboard.name = text.strip() or "Dashboard"

    # -- persistence -------------------------------------------------------------------------------

    def load_dashboard(self, dashboard: Dashboard) -> None:
        self.dashboard = dashboard
        self._name.setText(dashboard.name)
        self._rebuild_grid()
        self.refresh_tiles()
        missing = [name for name in dashboard.datasets() if not self._dataset_open(name)]
        if missing:
            self._status.setText(f"Not open: {', '.join(missing)} — open them, then Refresh all")
        else:
            self._status.setText(f"Opened “{dashboard.name}” ({len(dashboard.tiles)} chart(s))")

    def _dataset_open(self, name: str) -> bool:
        return any(d.name == name for d in self._catalog.datasets.values())
