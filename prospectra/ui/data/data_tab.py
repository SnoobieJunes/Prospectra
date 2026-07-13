# 2026-07-13 (P1): The Data workspace — virtualized grid on top, column profile cards below,
# with an honest status line (row/column counts, and "profiled on a sample" when true).

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSplitter, QTableView, QVBoxLayout, QWidget

from prospectra.core.catalog import Catalog
from prospectra.core.stats import TableProfile
from prospectra.ui.data.grid_model import DuckTableModel
from prospectra.ui.widgets.profile_cards import ProfileCardsPanel
from prospectra.ui.workers import run_in_pool

logger = logging.getLogger(__name__)


class DataTab(QWidget):
    def __init__(self, catalog: Catalog) -> None:
        super().__init__()
        self._catalog = catalog
        self._dataset_id: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self._status = QLabel("Open a data file or database table from the Sources panel.")
        self._status.setEnabled(False)
        layout.addWidget(self._status)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self._grid = QTableView()
        self._grid.setAlternatingRowColors(True)
        self._grid.horizontalHeader().setDefaultSectionSize(110)
        splitter.addWidget(self._grid)
        self._cards = ProfileCardsPanel()
        splitter.addWidget(self._cards)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

    def show_dataset(self, dataset_id: str) -> None:
        self._dataset_id = dataset_id
        ds = self._catalog.datasets[dataset_id]
        self._status.setText(f"{ds.name} — loading…")
        self._cards.clear()

        def load_shape() -> tuple[list[tuple[str, str]], int]:
            return self._catalog.describe(dataset_id), self._catalog.count_rows(dataset_id)

        run_in_pool(load_shape, on_result=self._shape_ready, on_error=self._failed)
        run_in_pool(
            self._catalog.profile, dataset_id, on_result=self._profile_ready, on_error=self._failed
        )

    # -- worker callbacks ---------------------------------------------------------------

    def _shape_ready(self, shape: tuple[list[tuple[str, str]], int]) -> None:
        if self._dataset_id is None:
            return
        columns, count = shape
        ds = self._catalog.datasets[self._dataset_id]
        dataset_id = self._dataset_id
        model = DuckTableModel(
            columns,
            count,
            lambda offset, limit: self._catalog.fetch_page(dataset_id, offset, limit),
        )
        self._grid.setModel(model)
        self._status.setText(f"{ds.name} — {count:,} rows · {len(columns)} columns")

    def _profile_ready(self, profile: TableProfile) -> None:
        self._cards.set_profile(profile)
        if profile.sampled:
            self._status.setText(
                self._status.text() + f" · profiled on a {profile.sample_size:,}-row sample"
            )

    def _failed(self, message: str) -> None:
        self._status.setText(f"Error: {message}")
        logger.error("Data tab error: %s", message)
