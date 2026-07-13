# 2026-07-13 (P0): Left dock — the connections/datasets tree. Placeholder items until the
# connector layer and catalog land in P1; the dock exists now so the shell layout is final.

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget, QTreeWidget, QTreeWidgetItem


class SourcesDock(QDockWidget):
    def __init__(self) -> None:
        super().__init__("Sources")
        self.setObjectName("dock_sources")
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        for label in ("Connections (P1)", "Datasets (P1)"):
            item = QTreeWidgetItem([label])
            item.setFlags(Qt.ItemFlag.NoItemFlags)  # visible but inert placeholder
            tree.addTopLevelItem(item)
        self.setWidget(tree)
