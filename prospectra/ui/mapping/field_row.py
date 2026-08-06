# 2026-07-31 (P7): One target column as a row — the mapper's drop target. Drag source columns
# onto it, chain transform chips, watch the live before → after, write down WHY (the note is the
# audit trail for "50 names for product name"). A row whose sources vanished upstream is painted
# red with the missing names — an upstream rename must be visible, not discovered on run.

from __future__ import annotations

import html

from PySide6.QtCore import QMimeData, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
)

from prospectra.core.mapping import FieldMap, Step, TargetColumn
from prospectra.core.mapping.transforms import TRANSFORMS, TRANSFORMS_BY_KEY
from prospectra.ui.dnd.drop_target import DropTargetMixin, drop_border_style
from prospectra.ui.dnd.mime import ColumnPayload, read_column
from prospectra.ui.mapping.transform_chip import TransformChip


class FieldRow(DropTargetMixin, QFrame):
    """One TargetColumn and (maybe) the FieldMap feeding it. Mutates `field_map` in place."""

    changed = Signal()

    def __init__(self, column: TargetColumn, field_map: FieldMap | None = None) -> None:
        super().__init__()
        self.column = column
        self.field_map = field_map or FieldMap(target=column.name)
        self._broken: list[str] = []
        self.setObjectName("field_row")
        self.setAcceptDrops(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 4)

        top = QHBoxLayout()
        required = " *" if column.required else ""
        # 2026-08-05: escaped — the name can come from a hostile CSV header or API payload, and
        # an unescaped rich-text QLabel lets it hide or spoof what the row claims to map.
        safe_name = html.escape(column.name)
        safe_type = html.escape(column.type)
        title = QLabel(f"<b>{safe_name}</b>{required}  <span>{safe_type}</span>")
        title.setToolTip("required — the mapping cannot save without it" if column.required else "")
        top.addWidget(title)
        self._sources = QLabel("")
        self._sources.setEnabled(False)
        top.addWidget(self._sources, 1)
        self._join = QLineEdit(self.field_map.join_with)
        self._join.setFixedWidth(48)
        self._join.setToolTip(
            "Joins multiple sources. Empty values are SKIPPED, not turned into blanks "
            "(a product with no colourway keeps its name)."
        )
        self._join.textChanged.connect(self._join_changed)
        top.addWidget(QLabel("join:"))
        top.addWidget(self._join)
        self._constant = QLineEdit(self.field_map.constant)
        self._constant.setPlaceholderText("or type a constant…")
        self._constant.setFixedWidth(130)
        self._constant.textChanged.connect(self._constant_changed)
        top.addWidget(self._constant)
        clear = QPushButton("✕")
        clear.setFixedWidth(24)
        clear.setToolTip("Clear this field's sources and transforms")
        clear.clicked.connect(self._clear)
        top.addWidget(clear)
        outer.addLayout(top)

        chips_row = QHBoxLayout()
        self._chips_layout = QHBoxLayout()
        chips_row.addLayout(self._chips_layout)
        self._add_transform = QToolButton()
        self._add_transform.setText("+ transform")
        self._add_transform.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._add_transform.setMenu(self._transform_menu())
        chips_row.addWidget(self._add_transform)
        chips_row.addStretch(1)
        self._preview = QLabel("")
        self._preview.setEnabled(False)
        chips_row.addWidget(self._preview)
        outer.addLayout(chips_row)

        self._note = QLineEdit(self.field_map.note)
        self._note.setPlaceholderText("why this mapping exists (the audit trail)")
        self._note.textChanged.connect(self._note_changed)
        outer.addWidget(self._note)

        self._chips: list[TransformChip] = []
        for step in self.field_map.steps:
            self._add_chip(step)
        self._refresh()

    # -- the menu: verified transforms up front, the raw-SQL hatch behind a disclosure ---------

    def _transform_menu(self) -> QMenu:
        menu = QMenu(self)
        advanced = QMenu("Advanced", menu)
        for transform in TRANSFORMS:
            action = QAction(f"{transform.label} — {transform.summary}", menu)
            action.triggered.connect(
                lambda _checked=False, key=transform.key: self._append_step(key)
            )
            (advanced if transform.status == "advanced" else menu).addAction(action)
        menu.addSeparator()
        menu.addMenu(advanced)  # `expression` lives here and is NEVER suggested
        return menu

    def _append_step(self, key: str) -> None:
        transform = TRANSFORMS_BY_KEY[key]
        step = Step(key=key, args={spec.name: spec.default for spec in transform.args})
        self.field_map.steps.append(step)
        chip = self._add_chip(step)
        self.changed.emit()
        if transform.args:
            chip._edit()  # a transform with args wants them typed now, not discovered later

    def _add_chip(self, step: Step) -> TransformChip:
        transform = TRANSFORMS_BY_KEY[step.key]
        chip = TransformChip(transform, step)
        chip.removed.connect(self._remove_chip)
        chip.edited.connect(self.changed.emit)
        self._chips.append(chip)
        self._chips_layout.addWidget(chip)
        return chip

    def _remove_chip(self, chip: TransformChip) -> None:
        # 2026-08-05: removed BY POSITION, not by value. `Step` is a dataclass with value
        # equality, so `steps.remove(chip.step)` on a chain like [trim, upper, trim] deleted the
        # FIRST trim when the user clicked the last chip — the displayed order and the compiled
        # order then disagreed, silently, for every order-sensitive chain.
        index = next((i for i, c in enumerate(self._chips) if c is chip), None)
        if index is None:
            return
        del self._chips[index]
        del self.field_map.steps[index]
        chip.setParent(None)
        self.changed.emit()

    # -- edits ---------------------------------------------------------------------------------

    def _join_changed(self, text: str) -> None:
        self.field_map.join_with = text
        self.changed.emit()

    def _constant_changed(self, text: str) -> None:
        self.field_map.constant = text
        self.changed.emit()

    def _note_changed(self, text: str) -> None:
        self.field_map.note = text
        self.changed.emit()

    def _clear(self) -> None:
        self.field_map.sources.clear()
        self.field_map.steps.clear()
        for chip in list(self._chips):
            self._chips.remove(chip)
            chip.setParent(None)
        self._refresh()
        self.changed.emit()

    def add_sources(self, columns: list[str]) -> None:
        for name in columns:
            if name not in self.field_map.sources:
                self.field_map.sources.append(name)
        self._refresh()
        self.changed.emit()

    def set_broken(self, missing: list[str]) -> None:
        """Sources that no longer exist upstream — painted red, named in the tooltip."""
        self._broken = list(missing)
        self._refresh()

    def set_preview(self, before: str, after: str) -> None:
        self._preview.setText(f"{before} → {after}")
        self._preview.setEnabled(True)

    @property
    def mapped(self) -> bool:
        return bool(self.field_map.sources or self.field_map.constant or self.field_map.steps)

    def _refresh(self) -> None:
        self._sources.setText(
            " + ".join(self.field_map.sources) if self.field_map.sources else "drop a column here"
        )
        self._join.setVisible(len(self.field_map.sources) > 1)
        if self._broken:
            self.setStyleSheet("#field_row { border: 2px solid #b71c1c; border-radius: 6px; }")
            self.setToolTip(
                "Missing upstream column(s): "
                + ", ".join(self._broken)
                + " — an upstream step renamed or dropped them."
            )
        else:
            self.setStyleSheet(drop_border_style("field_row", active=False))
            self.setToolTip("")

    # -- drops (protocol in DropTargetMixin) ---------------------------------------------------

    def _decode_drop(self, mime: QMimeData) -> ColumnPayload | None:
        return read_column(mime)

    def _payload_dropped(self, payload: ColumnPayload) -> None:
        self.add_sources(payload.columns)

    def _drop_active(self, active: bool) -> None:
        if not self._broken:
            self.setStyleSheet(drop_border_style("field_row", active=active))
