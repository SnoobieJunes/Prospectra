# 2026-07-14 (P5): One tile on a dashboard: a chart, its notes, and its exports.
#
# Export CSV is not a nicety — the dataviz method requires the numbers behind a chart to be
# reachable (colour must never be the only way to read a value), and "what's the actual number?"
# is the first question a dashboard gets asked. PNG export lives here because only the UI owns a
# matplotlib figure; the CSV path is core (`core/viz/export.py`) and is covered headless.
#
# A tile whose dataset is not open says so plainly, naming the file it needs, instead of rendering
# an empty chart that looks like "no data".

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from prospectra.core.viz import ChartData, ChartSpec, data_to_csv
from prospectra.ui.widgets.spec_chart import SpecChart

logger = logging.getLogger(__name__)


class ChartTile(QFrame):
    remove_requested = Signal(str)  # spec id

    def __init__(self, spec: ChartSpec) -> None:
        super().__init__()
        self.spec = spec
        self._data: ChartData | None = None
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(300)
        # Below this a chart is unreadable (axis labels collide, titles wrap to four lines), so the
        # grid scrolls instead of crushing tiles — seen crushed in a screenshot of the real window.
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        header = QHBoxLayout()
        # The chart draws its own title (and carries it into an exported PNG), so the header does
        # not repeat it — a duplicated, wrapped title ate a third of the tile's height on screen.
        # It only appears when there is no chart to title.
        self._title = QLabel()
        self._title.setWordWrap(True)
        self._title.setVisible(False)
        header.addWidget(self._title, 1)
        header.addStretch(1)
        csv_button = QPushButton("CSV")
        csv_button.setToolTip("Export the numbers behind this chart")
        csv_button.clicked.connect(self._export_csv)
        png_button = QPushButton("PNG")
        png_button.setToolTip("Export this chart as an image")
        png_button.clicked.connect(self._export_png)
        remove = QPushButton("✕")
        remove.setFixedWidth(28)
        remove.setToolTip("Remove this chart from the dashboard")
        remove.clicked.connect(lambda: self.remove_requested.emit(self.spec.id))
        header.addWidget(csv_button)
        header.addWidget(png_button)
        header.addWidget(remove)
        layout.addLayout(header)

        self._chart = SpecChart(self, height=2.6)
        layout.addWidget(self._chart, 1)

        self._status = QLabel(f"{spec.dataset} — loading…")
        self._status.setWordWrap(True)
        self._status.setEnabled(False)
        layout.addWidget(self._status)

    # -- content -------------------------------------------------------------------------------

    def set_data(self, data: ChartData) -> None:
        self._data = data
        self._chart.render(data)
        source = f"{self.spec.dataset}" if self.spec.dataset else "dataset"
        notes = "  ·  ".join(data.notes)
        self._status.setText(f"{source}{'  ·  ' + notes if notes else ''}")

    def set_unavailable(self, message: str) -> None:
        self._data = None
        self._status.setText(message)
        self._chart.setVisible(False)
        self._title.setText(f"<b>{self.spec.display_title}</b>")  # nothing else names the tile now
        self._title.setVisible(True)

    # -- exports -------------------------------------------------------------------------------

    def _export_csv(self) -> None:
        if self._data is None:
            QMessageBox.information(self, "Nothing to export", "This chart has no data loaded.")
            return
        default = f"{self.spec.display_title[:40].strip().replace(' ', '_')}.csv"
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export chart data", str(Path.home() / default), "CSV (*.csv)"
        )
        if not filename:
            return
        path = data_to_csv(self._data, filename)
        self._status.setText(f"Exported {path}")

    def _export_png(self) -> None:
        default = f"{self.spec.display_title[:40].strip().replace(' ', '_')}.png"
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export chart image", str(Path.home() / default), "PNG (*.png)"
        )
        if not filename:
            return
        # The figure carries its own caption (truncation / dropped-point notes), so the exported
        # image keeps its caveats — a PNG that outlives the app must not shed them.
        self._chart.figure.savefig(filename, dpi=160, facecolor=self._chart.figure.get_facecolor())
        self._status.setText(f"Exported {filename}")
