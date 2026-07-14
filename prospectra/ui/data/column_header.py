# 2026-07-14 (P5): The grid's header is the app's main drag source — this is where "drag a column
# into a chart shelf / into chat / onto New dataset" starts.
#
# Why a QHeaderView subclass rather than Qt's built-in section dragging: the built-in drag *moves
# sections* (reordering the view). We want a data drag carrying a column payload, so the drag is
# started by hand from mouseMoveEvent once the pointer has passed the platform's drag threshold.
# Below that threshold the press still behaves like a normal click/selection.
#
# A multi-column selection drags as one payload (that is what feeds the New-dataset drop zone),
# and the pressed column always leads it — dragging the column under the cursor must never send a
# different one just because something else was selected earlier.

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QDrag, QMouseEvent
from PySide6.QtWidgets import QApplication, QHeaderView, QTableView, QWidget

from prospectra.ui.dnd.mime import ColumnPayload, column_mime


class DraggableHeader(QHeaderView):
    """A horizontal header whose sections can be dragged out as column payloads."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setSectionsClickable(True)
        self.setHighlightSections(True)
        self._columns: list[tuple[str, str]] = []  # (name, dtype), in view order
        self._dataset_id = ""
        self._dataset = ""
        self._origin = ""
        self._press: QPoint | None = None
        self._press_section = -1

    def set_dataset(
        self, dataset_id: str, dataset: str, origin: str, columns: list[tuple[str, str]]
    ) -> None:
        self._dataset_id = dataset_id
        self._dataset = dataset
        self._origin = origin
        self._columns = columns

    # -- drag ----------------------------------------------------------------------------------

    def payload_for(self, sections: list[int]) -> ColumnPayload | None:
        picked = [s for s in sections if 0 <= s < len(self._columns)]
        if not picked or not self._dataset_id:
            return None
        return ColumnPayload(
            dataset_id=self._dataset_id,
            dataset=self._dataset,
            origin=self._origin,
            columns=[self._columns[s][0] for s in picked],
            dtypes=[self._columns[s][1] for s in picked],
        )

    def _selected_sections(self, pressed: int) -> list[int]:
        view = self.parentWidget()
        chosen: list[int] = []
        if isinstance(view, QTableView):
            model = view.selectionModel()
            if model is not None:
                chosen = sorted({i.column() for i in model.selectedColumns()})
        # The column under the cursor always leads — and travels alone when it wasn't selected.
        if pressed not in chosen:
            return [pressed]
        return [pressed, *[s for s in chosen if s != pressed]]

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.pos()
            self._press_section = self.logicalIndexAt(event.pos())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        travelled = (event.pos() - self._press).manhattanLength()
        if travelled < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        payload = self.payload_for(self._selected_sections(self._press_section))
        self._press = None
        if payload is None:
            return
        drag = QDrag(self)
        drag.setMimeData(column_mime(payload))
        drag.exec(Qt.DropAction.CopyAction)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._press = None
        super().mouseReleaseEvent(event)
