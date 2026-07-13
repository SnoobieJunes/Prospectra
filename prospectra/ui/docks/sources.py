# 2026-07-13 (P1): Sources dock, now real — a tree of opened datasets and database connections
# (with table children and honest status badges), plus Open File / Add Database actions.
# Replaced the P0 placeholder; emits signals only, so the main window owns all catalog work.
# 2026-07-13 (P0): original placeholder version.

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from prospectra.core.catalog import Dataset, SqlConnection

_KIND_ROLE = Qt.ItemDataRole.UserRole
_ID_ROLE = Qt.ItemDataRole.UserRole + 1


class SourcesDock(QDockWidget):
    open_file_requested = Signal()
    add_database_requested = Signal()
    dataset_activated = Signal(str)  # dataset id
    table_activated = Signal(str, str)  # connection id, table name

    def __init__(self) -> None:
        super().__init__("Sources")
        self.setObjectName("dock_sources")
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 4, 4, 4)

        buttons = QHBoxLayout()
        open_button = QPushButton("Open File…")
        open_button.clicked.connect(self.open_file_requested)
        add_button = QPushButton("Add Database…")
        add_button.clicked.connect(self.add_database_requested)
        buttons.addWidget(open_button)
        buttons.addWidget(add_button)
        layout.addLayout(buttons)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._datasets_root = QTreeWidgetItem(["Datasets"])
        self._connections_root = QTreeWidgetItem(["Connections"])
        self._tree.addTopLevelItem(self._datasets_root)
        self._tree.addTopLevelItem(self._connections_root)
        self._tree.expandAll()
        self._tree.itemActivated.connect(self._activated)
        self._tree.itemDoubleClicked.connect(self._activated)
        layout.addWidget(self._tree)
        self.setWidget(body)

    # -- population (called by the main window after catalog work completes) -----------

    def add_dataset(self, dataset: Dataset) -> None:
        item = QTreeWidgetItem([dataset.name])
        item.setToolTip(0, dataset.origin)
        item.setData(0, _KIND_ROLE, "dataset")
        item.setData(0, _ID_ROLE, dataset.id)
        self._datasets_root.addChild(item)
        self._datasets_root.setExpanded(True)

    def add_connection(self, connection: SqlConnection, tables: list[str]) -> None:
        label = connection.name
        if connection.status != "verified":
            label += "  (experimental)"  # untested dialect — honest badge per CLAUDE.md
        item = QTreeWidgetItem([label])
        item.setToolTip(0, connection.url)
        item.setData(0, _KIND_ROLE, "connection")
        item.setData(0, _ID_ROLE, connection.id)
        for table in tables:
            child = QTreeWidgetItem([table])
            child.setData(0, _KIND_ROLE, "table")
            child.setData(0, _ID_ROLE, connection.id)
            item.addChild(child)
        self._connections_root.addChild(item)
        self._connections_root.setExpanded(True)
        item.setExpanded(True)

    # -- interaction --------------------------------------------------------------------

    def _activated(self, item: QTreeWidgetItem, _column: int) -> None:
        kind = item.data(0, _KIND_ROLE)
        if kind == "dataset":
            self.dataset_activated.emit(item.data(0, _ID_ROLE))
        elif kind == "table":
            self.table_activated.emit(item.data(0, _ID_ROLE), item.text(0))
