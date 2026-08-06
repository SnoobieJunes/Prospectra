# 2026-07-31 (P7): Custom editors, keyed on `ParamField.kind` (never on node type — a descriptor
# drives the form, per the project's dialect rule). And the QLineEdit fallthrough for unknown
# kinds is GONE: it used to `str(dict)` a structured param into a text box and write the Python
# repr back on the next keystroke — data loss, not cosmetics. An unknown kind now renders a
# read-only notice that cannot write anything back.
# 2026-07-13 (P2): Generic params editor — renders a form straight from a node's `params_schema`,
# so a new node type needs no bespoke dialog (the modularity promise in CLAUDE.md: add one file,
# get a full UI). Edits write back to the node and announce a change.

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from prospectra.core.flow.graph import NodeInstance
from prospectra.core.flow.node import ParamField

# kind -> factory(editor, instance, field) -> widget. Consulted BEFORE the built-in kinds, so a
# package (ui/mapping registers "mapping_doc") or a plugin can own an editor without this file
# knowing it exists.
CUSTOM_EDITORS: dict[str, Callable[[ParamsEditor, NodeInstance, ParamField], QWidget]] = {}

# The kinds the generic factory below actually understands. Anything else must come from
# CUSTOM_EDITORS or it gets a read-only notice — never a QLineEdit.
_BUILTIN_KINDS = ("string", "columns", "expression", "choice", "bool", "int", "float", "path")


class ParamsEditor(QWidget):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        # 2026-07-31 (P7): the hosting workspace (FlowTab), for custom editors that need flow
        # services (upstream columns, previews). None when the editor stands alone.
        self.host: object | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._title = QLabel("Select a node")
        self._title.setStyleSheet("font-weight: 600;")
        self._layout.addWidget(self._title)
        self._form_host: QWidget | None = None
        self._instance: NodeInstance | None = None
        self._layout.addStretch(1)

    def set_node(self, instance: NodeInstance | None) -> None:
        self._instance = instance
        if self._form_host is not None:
            self._form_host.deleteLater()
            self._form_host = None
        if instance is None:
            self._title.setText("Select a node")
            return

        node = instance.node
        self._title.setText(type(node).display_name)
        host = QWidget()
        form = QFormLayout(host)
        form.setContentsMargins(0, 4, 0, 0)
        for field in type(node).params_schema:
            custom = CUSTOM_EDITORS.get(field.kind)
            if custom is not None:
                widget = custom(self, instance, field)
            elif field.kind in _BUILTIN_KINDS:
                widget = self._make_widget(
                    field.kind, field.name, node.params.get(field.name, ""), field.choices
                )
            else:
                # No editor knows this kind. A disabled label can NOT corrupt the value the way
                # the old QLineEdit fallthrough did (str(dict) written back on focus-out).
                widget = QLabel(f"(no editor for {field.kind!r} — value left untouched)")
                widget.setEnabled(False)
            if field.help:
                widget.setToolTip(field.help)
            form.addRow(field.label, widget)
        if not type(node).params_schema:
            note = QLabel("No settings — this node just combines its inputs.")
            note.setEnabled(False)
            form.addRow(note)
        self._layout.insertWidget(1, host)
        self._form_host = host

    # -- widget factory ------------------------------------------------------------------

    def _make_widget(self, kind: str, name: str, value: Any, choices: tuple[str, ...]) -> QWidget:
        if kind == "choice":
            combo = QComboBox()
            combo.addItems(list(choices))
            if str(value) in choices:
                combo.setCurrentText(str(value))
            combo.currentTextChanged.connect(lambda text, n=name: self._set(n, text))
            return combo
        if kind == "bool":
            box = QCheckBox()
            box.setChecked(bool(value))
            box.toggled.connect(lambda checked, n=name: self._set(n, checked))
            return box
        if kind == "int":
            spin = QSpinBox()
            spin.setRange(1, 100_000_000)
            spin.setValue(int(value or 0) or 1)
            spin.valueChanged.connect(lambda v, n=name: self._set(n, v))
            return spin
        if kind == "float":
            dspin = QDoubleSpinBox()
            dspin.setRange(0.0, 1_000_000.0)
            dspin.setDecimals(2)
            dspin.setValue(float(value or 0.0))
            dspin.valueChanged.connect(lambda v, n=name: self._set(n, v))
            return dspin
        if kind == "path":
            host = QWidget()
            row = QHBoxLayout(host)
            row.setContentsMargins(0, 0, 0, 0)
            line = QLineEdit(str(value))
            line.textChanged.connect(lambda text, n=name: self._set(n, text))
            browse = QPushButton("…")
            browse.setFixedWidth(30)
            browse.clicked.connect(lambda _checked=False, edit=line, n=name: self._browse(edit, n))
            row.addWidget(line)
            row.addWidget(browse)
            return host
        line = QLineEdit(str(value))
        line.textChanged.connect(lambda text, n=name: self._set(n, text))
        return line

    def _browse(self, edit: QLineEdit, name: str) -> None:
        is_output = self._instance is not None and self._instance.node.category == "output"
        if is_output:
            path, _ = QFileDialog.getSaveFileName(self, "Write output to", edit.text())
        else:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Choose input file",
                edit.text(),
                "Data files (*.csv *.tsv *.txt *.json *.jsonl *.ndjson *.parquet);;All files (*)",
            )
        if path:
            edit.setText(path)  # textChanged writes it back through _set

    def _set(self, name: str, value: Any) -> None:
        if self._instance is None:
            return
        self._instance.node.params[name] = value
        self.changed.emit()
