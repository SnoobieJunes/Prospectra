# 2026-07-14 (P5): Context chips for the chat dock — the P4 deferral, now built (Deviations.md,
# "P4: no drag-in context chips in the chat dock").
#
# A chip is a *pointer*, not data: dropping a column adds "the column `temperature` of dataset
# `ice_cream_sales`" to the question's preamble, so the assistant knows what to look at and then
# looks it up with its own tools, under the privacy level in force. Nothing about the drop widens
# what the model may see — the privacy gate is upstream of this and stays the only thing that
# decides. Dropping a column at SCHEMA_ONLY still sends no values.

from __future__ import annotations

from PySide6.QtCore import QMimeData, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from prospectra.ui.dnd.drop_target import DropTargetMixin
from prospectra.ui.dnd.mime import read_column, read_dataset, read_finding


class Chip(QFrame):
    """One piece of context the next question carries."""

    removed = Signal(object)  # self

    def __init__(self, kind: str, label: str, context: str) -> None:
        super().__init__()
        self.kind = kind  # "column" | "dataset" | "finding"
        self.context = context  # the sentence handed to the model
        self.setObjectName("chip")
        self.setStyleSheet(
            "#chip { border: 1px solid palette(mid); border-radius: 9px; background: "
            "palette(alternate-base); }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 1, 2, 1)
        text = QLabel(label)
        text.setToolTip(context)
        layout.addWidget(text)
        close = QPushButton("✕")
        close.setFlat(True)
        close.setFixedWidth(18)
        close.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(close)


class ChipBar(DropTargetMixin, QWidget):
    """The strip of chips above the chat input; also the dock's drop target.

    2026-07-31 (P7): drop plumbing moved to DropTargetMixin."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._hint = QLabel("Drag a column, dataset, or finding here to ask about it")
        self._hint.setEnabled(False)
        self._layout.addWidget(self._hint)
        self._layout.addStretch(1)
        self._chips: list[Chip] = []

    # -- state ---------------------------------------------------------------------------------

    @property
    def chips(self) -> list[Chip]:
        return list(self._chips)

    def add_chip(self, kind: str, label: str, context: str) -> Chip:
        chip = Chip(kind, label, context)
        chip.removed.connect(self._remove)
        self._chips.append(chip)
        self._layout.insertWidget(len(self._chips) - 1, chip)
        self._hint.setVisible(False)
        self.changed.emit()
        return chip

    def _remove(self, chip: Chip) -> None:
        self._chips.remove(chip)
        chip.setParent(None)
        self._hint.setVisible(not self._chips)
        self.changed.emit()

    def clear(self) -> None:
        for chip in list(self._chips):
            self._remove(chip)

    def preamble(self) -> str:
        """The context sentence prepended to the next question (empty when there are no chips)."""
        if not self._chips:
            return ""
        lines = "\n".join(f"- {chip.context}" for chip in self._chips)
        return f"Context I am asking about:\n{lines}\n\n"

    # -- drops (protocol in DropTargetMixin) ---------------------------------------------------

    def _decode_drop(self, mime: QMimeData) -> QMimeData | None:
        if read_column(mime) or read_dataset(mime) or read_finding(mime):
            return mime  # the payload is whichever of the three kinds decodes; chip() dispatches
        return None

    def _payload_dropped(self, mime: QMimeData) -> None:
        self.payload_chip(mime)

    def payload_chip(self, mime) -> Chip | None:
        column = read_column(mime)
        if column is not None:
            label = column.as_text()
            return self.add_chip(
                "column",
                f"▦ {label}",
                f"the column(s) {label} of the dataset {column.dataset!r}",
            )
        dataset = read_dataset(mime)
        if dataset is not None:
            return self.add_chip(
                "dataset", f"▤ {dataset.dataset}", f"the dataset {dataset.dataset!r}"
            )
        finding = read_finding(mime)
        if finding is not None:
            return self.add_chip(
                "finding",
                f"◆ {finding.title}",
                f"the finding {finding.title!r}: {finding.headline} "
                f"({finding.effect_name} = {finding.effect:.2f}, q = {finding.q_value:.2g})",
            )
        return None
