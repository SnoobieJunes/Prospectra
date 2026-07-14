# 2026-07-14 (P5): Two drag-and-drop roles land here. The tree is a *drag source* (a dataset can be
# dragged into the chat or onto a chart), and the "New dataset" strip below it is a *drop target*:
# drop columns on it and Prospectra derives a dataset from them AND writes the flow that produces
# it (Input → Select → Output), so the derivation is visible and editable, never hidden magic.
# 2026-07-13 (P1): Sources dock, now real — a tree of opened datasets and database connections
# (with table children and honest status badges), plus Open File / Add Database actions.
# Replaced the P0 placeholder; emits signals only, so the main window owns all catalog work.
# 2026-07-13 (P0): original placeholder version.

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from prospectra.core.catalog import Dataset, SqlConnection
from prospectra.ui.dnd.mime import DatasetPayload, dataset_mime, read_column

_KIND_ROLE = Qt.ItemDataRole.UserRole
_ID_ROLE = Qt.ItemDataRole.UserRole + 1
_NAME_ROLE = Qt.ItemDataRole.UserRole + 2
_ORIGIN_ROLE = Qt.ItemDataRole.UserRole + 3


class _SourceTree(QTreeWidget):
    """Datasets here are draggable — into chat, onto a chart, anywhere that reads a dataset."""

    def mimeData(self, items):
        for item in items:
            if item.data(0, _KIND_ROLE) == "dataset":
                return dataset_mime(
                    DatasetPayload(
                        dataset_id=str(item.data(0, _ID_ROLE)),
                        dataset=str(item.data(0, _NAME_ROLE)),
                        origin=str(item.data(0, _ORIGIN_ROLE) or ""),
                    )
                )
        return super().mimeData(items)


class NewDatasetZone(QLabel):
    """Drop columns here to derive a dataset from them (and get the flow that builds it)."""

    columns_dropped = Signal(str, list)  # source dataset id, column names

    _IDLE = "+  New dataset\nDrop columns here"
    _ACTIVE = "+  Release to build a dataset from these columns"

    def __init__(self) -> None:
        super().__init__(self._IDLE)
        self.setObjectName("new_dataset_zone")
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setMinimumHeight(58)
        self._style(active=False)

    def _style(self, *, active: bool) -> None:
        # Dashed border reads as "a place things go" without needing an icon set.
        colour = "#2a78d6" if active else "palette(mid)"
        weight = "bold" if active else "normal"
        self.setStyleSheet(
            f"#new_dataset_zone {{ border: 2px dashed {colour}; border-radius: 6px; "
            f"padding: 6px; font-weight: {weight}; }}"
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if read_column(event.mimeData()) is not None:
            event.acceptProposedAction()
            self.setText(self._ACTIVE)
            self._style(active=True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self.setText(self._IDLE)
        self._style(active=False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        payload = read_column(event.mimeData())
        self.setText(self._IDLE)
        self._style(active=False)
        if payload is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.columns_dropped.emit(payload.dataset_id, payload.columns)


class SourcesDock(QDockWidget):
    open_file_requested = Signal()
    add_database_requested = Signal()
    add_api_requested = Signal()  # 2026-07-14 (P6)
    scrape_requested = Signal()  # 2026-07-14 (P5)
    dataset_activated = Signal(str)  # dataset id
    table_activated = Signal(str, str)  # connection id, table name
    new_dataset_requested = Signal(str, list)  # 2026-07-14 (P5): source dataset id, columns

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
        api_button = QPushButton("Add API…")
        api_button.clicked.connect(self.add_api_requested)
        scrape_button = QPushButton("Scrape Web…")
        scrape_button.clicked.connect(self.scrape_requested)
        buttons.addWidget(open_button)
        buttons.addWidget(add_button)
        buttons.addWidget(api_button)
        buttons.addWidget(scrape_button)
        layout.addLayout(buttons)

        self._tree = _SourceTree()
        self._tree.setHeaderHidden(True)
        self._tree.setDragEnabled(True)
        self._tree.setDragDropMode(QTreeWidget.DragDropMode.DragOnly)
        self._datasets_root = QTreeWidgetItem(["Datasets"])
        self._connections_root = QTreeWidgetItem(["Connections"])
        self._tree.addTopLevelItem(self._datasets_root)
        self._tree.addTopLevelItem(self._connections_root)
        self._tree.expandAll()
        self._tree.itemActivated.connect(self._activated)
        self._tree.itemDoubleClicked.connect(self._activated)
        layout.addWidget(self._tree, 1)

        self._zone = NewDatasetZone()
        self._zone.columns_dropped.connect(self.new_dataset_requested)
        layout.addWidget(self._zone)
        self.setWidget(body)

    # -- population (called by the main window after catalog work completes) -----------

    def add_dataset(self, dataset: Dataset) -> None:
        item = QTreeWidgetItem([dataset.name])
        item.setToolTip(0, dataset.origin)
        item.setData(0, _KIND_ROLE, "dataset")
        item.setData(0, _ID_ROLE, dataset.id)
        item.setData(0, _NAME_ROLE, dataset.name)
        item.setData(0, _ORIGIN_ROLE, dataset.origin)
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

    # -- test / automation seam ----------------------------------------------------------

    def drop_columns(self, dataset_id: str, columns: list[str]) -> None:
        """Same effect as a column drop on the zone, without synthesising a Qt drag."""
        self._zone.columns_dropped.emit(dataset_id, columns)
