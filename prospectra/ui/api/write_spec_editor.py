# 2026-07-31 (P7): The inline editor for a `write_spec` param — the REST Write node's form.
# Registered under the param KIND (like mapping_doc), not the node type. The form's job is to
# make the rails visible: the caps and the mode are right here next to the URL, and POST's
# "may duplicate on retry" acknowledgement is a checkbox the user must tick, not a docstring.

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from prospectra.core.flow.graph import NodeInstance
from prospectra.core.flow.node import ParamField
from prospectra.core.http import AUTH_KINDS, Auth
from prospectra.core.http.write import WRITE_METHODS, WRITE_MODES, WriteSpec

logger = logging.getLogger(__name__)


class WriteSpecEditor(QWidget):
    """Edits the node's `spec` param dict in place; every change writes back immediately."""

    def __init__(self, editor, instance: NodeInstance, field: ParamField) -> None:
        super().__init__()
        self._editor = editor
        self._instance = instance
        self._field = field
        self._readable = True
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        try:
            spec = self._spec()
        except ValueError as exc:
            # A spec written by a newer build: show why, change NOTHING. Rendering the form with
            # blank defaults would let the first keystroke overwrite a document this build cannot
            # even read — which is the destruction the schema guard exists to prevent.
            self._readable = False
            notice = QLabel(f"This destination was written by a newer Prospectra.\n{exc}")
            notice.setWordWrap(True)
            notice.setEnabled(False)
            form.addRow(notice)
            return
        self._url = QLineEdit(spec.url_template)
        self._url.setPlaceholderText("https://api.example.com/products/{styleCode}")
        form.addRow("URL template", self._url)
        self._method = QComboBox()
        self._method.addItems(list(WRITE_METHODS))
        self._method.setCurrentText(spec.method.upper())
        form.addRow("Method", self._method)
        self._key = QLineEdit(spec.key_column)
        self._key.setToolTip(
            "The column that names a row — it fills the {placeholder} and makes every "
            "failure attributable to a specific row."
        )
        form.addRow("Key column", self._key)
        self._mode = QComboBox()
        self._mode.addItems(list(WRITE_MODES))
        self._mode.setCurrentText(spec.mode)
        self._mode.setToolTip(
            "per_row (default): one request per row, failures name their row.\n"
            "batch: chunks of rows per request — faster, failures blame the whole chunk."
        )
        form.addRow("Mode", self._mode)
        self._max_rows = QSpinBox()
        self._max_rows.setRange(1, 1_000_000)
        self._max_rows.setValue(spec.max_rows)
        self._max_rows.setToolTip("Hard cap per run; hitting it is reported, never silent.")
        form.addRow("Row cap", self._max_rows)
        self._rate = QDoubleSpinBox()
        self._rate.setRange(0.0, 100.0)
        self._rate.setDecimals(1)
        self._rate.setValue(spec.rate_per_sec)
        self._rate.setToolTip("Requests per second to this host (0 = no throttle).")
        form.addRow("Rate/sec", self._rate)
        self._auth_kind = QComboBox()
        self._auth_kind.addItems(list(AUTH_KINDS))
        self._auth_kind.setCurrentText(spec.auth.kind)
        form.addRow("Auth", self._auth_kind)
        # 2026-08-05: the kind's companion field. Without it, picking header/query/basic gave a
        # spec that validate() then refused ("header auth needs the header's name") with no way
        # to supply the name from the UI — a dead end the user could not get out of.
        self._auth_extra = QLineEdit(spec.auth.user or spec.auth.header or spec.auth.param)
        self._auth_extra.setPlaceholderText(
            "(basic: username · header: header name · query: parameter name)"
        )
        form.addRow("User / name", self._auth_extra)
        self._secret_ref = QLineEdit(spec.auth.secret_ref)
        self._secret_ref.setPlaceholderText("keychain entry, e.g. api:pim")
        form.addRow("Secret ref", self._secret_ref)
        self._ack = QCheckBox("POST may create duplicates on retry — I understand")
        self._ack.setChecked(spec.post_acknowledged)
        self._ack.setToolTip(
            "The Idempotency-Key sent with POST is honoured by Stripe-class APIs and ignored "
            "by most. A retry against an API that ignores it can create the row twice."
        )
        form.addRow(self._ack)

        for signal in (
            self._url.textChanged,
            self._method.currentTextChanged,
            self._key.textChanged,
            self._mode.currentTextChanged,
            self._secret_ref.textChanged,
            self._auth_extra.textChanged,
            self._auth_kind.currentTextChanged,
        ):
            signal.connect(lambda *_: self._write_back())
        self._max_rows.valueChanged.connect(lambda *_: self._write_back())
        self._rate.valueChanged.connect(lambda *_: self._write_back())
        self._ack.toggled.connect(lambda *_: self._write_back())

    def _spec(self) -> WriteSpec:
        return WriteSpec.from_dict(self._instance.node.params.get(self._field.name) or {})

    def _write_back(self) -> None:
        # 2026-08-05: a spec this build cannot read is left ALONE (see __init__).
        if not self._readable:
            logger.warning("Refusing to edit a write spec written by a newer build")
            return
        current = self._spec()
        current.url_template = self._url.text().strip()
        current.method = self._method.currentText()
        current.key_column = self._key.text().strip()
        current.mode = self._mode.currentText()
        current.max_rows = self._max_rows.value()
        current.rate_per_sec = self._rate.value()
        current.post_acknowledged = self._ack.isChecked()
        kind = self._auth_kind.currentText()
        extra = self._auth_extra.text().strip()
        current.auth = Auth(
            kind=kind,
            secret_ref=self._secret_ref.text().strip(),
            user=extra if kind == "basic" else "",
            header=extra if kind == "header" else "",
            param=extra if kind == "query" else "",
        )
        self._instance.node.params[self._field.name] = current.to_dict()
        self._editor.changed.emit()
