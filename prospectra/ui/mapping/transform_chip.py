# 2026-07-31 (P7): One transform as a chip — "Split and keep part (- , 1)" with a ✕ — plus the
# generic args dialog rendered straight from the transform's ArgSpec tuple (the descriptor-drives-
# the-form rule: add a transform in core, get its UI here for free, no new dialog class).

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from prospectra.core.mapping import Step, Transform, coerce_args
from prospectra.core.mapping.transforms import MAX_INLINE_PAIRS


class TransformArgsDialog(QDialog):
    """Edit one step's args — every widget comes from the ArgSpec kind, nothing is bespoke."""

    def __init__(
        self, transform: Transform, args: dict[str, Any], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(transform.label)
        self._transform = transform
        self._widgets: dict[str, QWidget] = {}

        layout = QVBoxLayout(self)
        summary = QLabel(transform.summary)
        summary.setWordWrap(True)
        layout.addWidget(summary)
        form = QFormLayout()
        for spec in transform.args:
            value = args.get(spec.name, spec.default)
            widget: QWidget
            if spec.kind == "int":
                spin = QSpinBox()
                spin.setRange(spec.min_value or 0, spec.max_value or 100_000_000)
                try:
                    spin.setValue(int(value))
                except (TypeError, ValueError):
                    spin.setValue(spec.min_value or 0)
                widget = spin
            elif spec.kind == "choice":
                combo = QComboBox()
                combo.addItems(list(spec.choices))
                if str(value) in spec.choices:
                    combo.setCurrentText(str(value))
                widget = combo
            elif spec.kind == "pairs":
                widget = self._pairs_table(value if isinstance(value, list) else [])
            elif spec.kind == "path":
                widget = self._path_row(str(value))
            else:
                widget = QLineEdit(str(value))
            if spec.help:
                widget.setToolTip(spec.help)
            self._widgets[spec.name] = widget
            form.addRow(spec.label, widget)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        self._problem = QLabel("")
        self._problem.setWordWrap(True)
        self._problem.setStyleSheet("color: #b71c1c;")
        layout.addWidget(self._problem)
        layout.addWidget(buttons)

    def _pairs_table(self, pairs: list[Any]) -> QWidget:
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, 0, 0, 0)
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["From", "To"])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        for pair in pairs[:MAX_INLINE_PAIRS]:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(str(pair[0])))
            table.setItem(row, 1, QTableWidgetItem(str(pair[1])))
        add = QPushButton("+ Add pair")
        add.clicked.connect(lambda: table.insertRow(table.rowCount()))
        column.addWidget(table)
        column.addWidget(add)
        host.setProperty("pairs_table", table)
        return host

    def _path_row(self, value: str) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        line = QLineEdit(value)
        browse = QPushButton("…")
        browse.setFixedWidth(30)

        def pick() -> None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Choose crosswalk file", line.text(), "CSV files (*.csv);;All files (*)"
            )
            if path:
                line.setText(path)

        browse.clicked.connect(pick)
        row.addWidget(line)
        row.addWidget(browse)
        host.setProperty("path_line", line)
        return host

    def args(self) -> dict[str, Any]:
        raw: dict[str, Any] = {}
        for spec in self._transform.args:
            widget = self._widgets[spec.name]
            if isinstance(widget, QSpinBox):
                raw[spec.name] = widget.value()
            elif isinstance(widget, QComboBox):
                raw[spec.name] = widget.currentText()
            elif isinstance(widget, QLineEdit):
                raw[spec.name] = widget.text()
            elif widget.property("pairs_table") is not None:
                table = widget.property("pairs_table")
                pairs: list[list[str]] = []
                for row in range(table.rowCount()):
                    key_item, value_item = table.item(row, 0), table.item(row, 1)
                    key = key_item.text().strip() if key_item else ""
                    if key:
                        pairs.append([key, value_item.text() if value_item else ""])
                raw[spec.name] = pairs
            elif widget.property("path_line") is not None:
                raw[spec.name] = widget.property("path_line").text().strip()
        return raw

    def _accept_if_valid(self) -> None:
        try:
            coerce_args(self._transform, self.args())  # the same boundary compile enforces
        except ValueError as exc:
            self._problem.setText(str(exc))
            return
        self.accept()


class TransformChip(QFrame):
    """One step in a field's chain. Click to edit its args, ✕ to remove."""

    removed = Signal(object)  # self
    edited = Signal()

    def __init__(self, transform: Transform, step: Step) -> None:
        super().__init__()
        self.transform = transform
        self.step = step
        self.setObjectName("transform_chip")
        self.setStyleSheet(
            "#transform_chip { border: 1px solid palette(mid); border-radius: 9px; "
            "background: palette(alternate-base); }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 1, 2, 1)
        self._text = QPushButton(self._label())
        self._text.setFlat(True)
        self._text.setToolTip(transform.summary)
        self._text.clicked.connect(self._edit)
        layout.addWidget(self._text)
        close = QPushButton("✕")
        close.setFlat(True)
        close.setFixedWidth(18)
        close.setToolTip("Remove this transform")
        close.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(close)

    def _label(self) -> str:
        shown = {k: v for k, v in self.step.args.items() if v not in ("", [], None)}
        if not shown:
            return self.transform.label
        rendered = ", ".join(str(v) for v in shown.values())
        return f"{self.transform.label} ({rendered[:24]})"

    def _edit(self) -> None:
        if not self.transform.args:
            return  # nothing to edit (trim, upper, …)
        dialog = TransformArgsDialog(self.transform, self.step.args, self)
        if dialog.exec():
            self.step.args = dialog.args()
            self._text.setText(self._label())
            self.edited.emit()
