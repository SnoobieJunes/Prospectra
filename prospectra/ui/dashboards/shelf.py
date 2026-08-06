# 2026-07-14 (P5): Chart shelves — the drop targets a column lands on. One shelf, one role (X, Y,
# Colour). This is the Tableau idiom, and it is the reason the chart builder needs no dialog: the
# shelf you drop on *is* the question you are answering.
#
# A shelf knows the dtype it received, so the builder can keep the mark honest (you cannot ask for
# a histogram of a text column, and a scatter needs two numeric shelves).

from __future__ import annotations

from PySide6.QtCore import QMimeData, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from prospectra.ui.dnd.drop_target import DropTargetMixin, drop_border_style
from prospectra.ui.dnd.mime import ColumnPayload, read_column

NUMERIC_TYPES = (
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
    "FLOAT",
    "DOUBLE",
    "DECIMAL",
    "REAL",
)


def is_numeric(dtype: str) -> bool:
    upper = dtype.upper()
    return any(upper.startswith(t) for t in NUMERIC_TYPES)


class ColumnShelf(DropTargetMixin, QFrame):
    """Drop one column here. Emits (dataset_id, column, dtype) — or empty strings when cleared.

    2026-07-31 (P7): drop plumbing moved to DropTargetMixin (shared with every other target)."""

    changed = Signal(str, str, str)

    def __init__(self, role: str, hint: str = "") -> None:
        super().__init__()
        self.role = role
        self._hint = hint or f"drop a column for {role}"
        self.column = ""
        self.dtype = ""
        self.dataset_id = ""

        self.setObjectName("shelf")
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        self._role_label = QLabel(f"<b>{role}</b>")
        self._role_label.setMinimumWidth(46)
        self._value = QLabel(self._hint)
        self._value.setEnabled(False)
        self._clear = QPushButton("✕")
        self._clear.setFixedWidth(24)
        self._clear.setToolTip(f"Clear the {role} shelf")
        self._clear.setVisible(False)
        self._clear.clicked.connect(self.clear)
        layout.addWidget(self._role_label)
        layout.addWidget(self._value, 1)
        layout.addWidget(self._clear)
        self._drop_active(False)

    def _drop_active(self, active: bool) -> None:
        self.setStyleSheet(drop_border_style("shelf", active=active, width=1, radius=4))

    # -- state ---------------------------------------------------------------------------------

    def set_column(self, dataset_id: str, column: str, dtype: str) -> None:
        self.dataset_id = dataset_id
        self.column = column
        self.dtype = dtype
        self._value.setText(
            f"{column}   <span style='opacity:0.6'>{dtype}</span>" if column else ""
        )
        self._value.setEnabled(bool(column))
        self._clear.setVisible(bool(column))
        self.changed.emit(dataset_id, column, dtype)

    def clear(self) -> None:
        self.dataset_id = ""
        self.column = ""
        self.dtype = ""
        self._value.setText(self._hint)
        self._value.setEnabled(False)
        self._clear.setVisible(False)
        self.changed.emit("", "", "")

    @property
    def numeric(self) -> bool:
        return bool(self.column) and is_numeric(self.dtype)

    # -- drops (protocol in DropTargetMixin) ---------------------------------------------------

    def _decode_drop(self, mime: QMimeData) -> ColumnPayload | None:
        return read_column(mime)

    def _payload_dropped(self, payload: ColumnPayload) -> None:
        self.set_column(payload.dataset_id, payload.column, payload.dtype)
