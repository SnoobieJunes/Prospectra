# 2026-07-31 (P7): The request half of the API playground — a Postman-style form that edits an
# `HttpRequest` document. Params and Headers get real key-value grids (neither had ANY UI before
# P7: a mapping's headers could be persisted but never viewed or typed).
#
# The curl preview beside the form shows what will actually be sent, with credentials masked —
# `to_curl` is never handed the secret, so the preview *cannot* leak it. The token typed in the
# Auth tab goes to `send()` at send time and to the OS keychain on save; never into the document.

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from prospectra.core.http import AUTH_KINDS, BODY_KINDS, METHODS, Auth, HttpRequest, to_curl


class KeyValueGrid(QWidget):
    """A two-column editable grid for params/headers, with add/remove and dict round-tripping."""

    changed = Signal()

    def __init__(self, key_label: str, value_label: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels([key_label, value_label])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.cellChanged.connect(lambda *_: self.changed.emit())
        layout.addWidget(self._table, 1)

        buttons = QHBoxLayout()
        add = QPushButton("+ Add")
        add.clicked.connect(self.add_row)
        remove = QPushButton("- Remove")
        remove.clicked.connect(self._remove_current)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def add_row(self, key: str = "", value: str = "") -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(key))
        self._table.setItem(row, 1, QTableWidgetItem(value))

    def _remove_current(self) -> None:
        row = self._table.currentRow()
        if row >= 0:
            self._table.removeRow(row)
            self.changed.emit()

    def pairs(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for row in range(self._table.rowCount()):
            key_item = self._table.item(row, 0)
            value_item = self._table.item(row, 1)
            key = key_item.text().strip() if key_item else ""
            if key:
                result[key] = value_item.text() if value_item else ""
        return result

    def set_pairs(self, pairs: dict[str, str]) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for key, value in pairs.items():
            self.add_row(key, value)
        self._table.blockSignals(False)
        self.changed.emit()


class RequestEditor(QWidget):
    """Edits one HttpRequest. `request()` is the seam tests (and the playground) read."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        top = QHBoxLayout()
        self._method = QComboBox()
        self._method.addItems(list(METHODS))
        self._url = QLineEdit()
        self._url.setPlaceholderText("https://api.example.com/v1/products")
        top.addWidget(self._method)
        top.addWidget(self._url, 1)
        layout.addLayout(top)

        self._tabs = QTabWidget()
        self._params = KeyValueGrid("Parameter", "Value")
        self._headers = KeyValueGrid("Header", "Value")
        self._tabs.addTab(self._params, "Params")
        self._tabs.addTab(self._headers, "Headers")
        self._tabs.addTab(self._make_auth_tab(), "Auth")
        self._tabs.addTab(self._make_body_tab(), "Body")
        layout.addWidget(self._tabs, 1)

        self._curl = QPlainTextEdit()
        self._curl.setReadOnly(True)
        self._curl.setMaximumHeight(84)
        self._curl.setPlaceholderText("The request, as curl — credentials always masked.")
        layout.addWidget(self._curl)

        for signal in (
            self._method.currentTextChanged,
            self._url.textChanged,
            self._params.changed,
            self._headers.changed,
        ):
            signal.connect(self._emit_changed)
        self.changed.connect(self._refresh_curl)

    def _make_auth_tab(self) -> QWidget:
        host = QWidget()
        form = QFormLayout(host)
        self._auth_kind = QComboBox()
        for kind in AUTH_KINDS:
            self._auth_kind.addItem(kind, kind)
        self._auth_kind.currentIndexChanged.connect(self._auth_changed)
        self._auth_extra = QLineEdit()
        self._auth_extra.setPlaceholderText(
            "(basic: username · header: header name · query: param)"
        )
        self._secret_ref = QLineEdit()
        self._secret_ref.setPlaceholderText("keychain entry name, e.g. api:my-service")
        self._token = QLineEdit()
        self._token.setEchoMode(QLineEdit.EchoMode.Password)
        self._token.setPlaceholderText("used to send; saved to your OS keychain, never the project")
        form.addRow("Auth", self._auth_kind)
        form.addRow("User / name", self._auth_extra)
        form.addRow("Secret ref", self._secret_ref)
        form.addRow("Token / password", self._token)
        for signal in (
            self._auth_kind.currentIndexChanged,
            self._auth_extra.textChanged,
            self._secret_ref.textChanged,
        ):
            signal.connect(self._emit_changed)
        self._auth_changed()
        return host

    def _make_body_tab(self) -> QWidget:
        host = QWidget()
        column = QVBoxLayout(host)
        self._body_kind = QComboBox()
        for kind in BODY_KINDS:
            self._body_kind.addItem(kind, kind)
        self._body = QPlainTextEdit()
        self._body.setPlaceholderText(
            'json: {"q": "shirts"} · form: a=1&b=2 · text: anything.\n'
            "{{secret:<ref>}} anywhere is replaced from your keychain at send time."
        )
        column.addWidget(self._body_kind)
        column.addWidget(self._body, 1)
        self._body_kind.currentIndexChanged.connect(self._emit_changed)
        self._body.textChanged.connect(self._emit_changed)
        return host

    # -- state -----------------------------------------------------------------------------------

    def _auth_changed(self) -> None:
        kind = str(self._auth_kind.currentData())
        self._auth_extra.setEnabled(kind in ("basic", "header", "query"))
        self._secret_ref.setEnabled(kind != "none")
        self._token.setEnabled(kind != "none")

    def _emit_changed(self, *_args: object) -> None:
        self.changed.emit()

    def _refresh_curl(self) -> None:
        try:
            self._curl.setPlainText(to_curl(self.request()))
        except ValueError:
            self._curl.setPlainText("")  # a half-typed request has no meaningful curl yet

    def request(self) -> HttpRequest:
        kind = str(self._auth_kind.currentData())
        extra = self._auth_extra.text().strip()
        body_kind = str(self._body_kind.currentData())
        return HttpRequest(
            method=self._method.currentText(),
            url=self._url.text().strip(),
            headers=self._headers.pairs(),
            params=self._params.pairs(),
            body_kind=body_kind,
            body=self._body.toPlainText() if body_kind != "none" else "",
            auth=Auth(
                kind=kind,
                secret_ref=self._secret_ref.text().strip(),
                user=extra if kind == "basic" else "",
                header=extra if kind == "header" else "",
                param=extra if kind == "query" else "",
            ),
        )

    def set_request(self, request: HttpRequest) -> None:
        # 2026-08-05: the typed token is cleared with the rest of the form. It used to survive a
        # request switch, and `_send_with_keychain` PREFERS the typed token over the request's own
        # secret_ref — so loading a saved request for another service and pressing Send delivered
        # the previous service's credential to it.
        self._token.clear()
        self._method.setCurrentText(request.method.upper())
        self._url.setText(request.url)
        self._params.set_pairs(request.params)
        self._headers.set_pairs(request.headers)
        self._auth_kind.setCurrentIndex(max(0, self._auth_kind.findData(request.auth.kind)))
        self._auth_extra.setText(request.auth.user or request.auth.header or request.auth.param)
        self._secret_ref.setText(request.auth.secret_ref)
        self._body_kind.setCurrentIndex(max(0, self._body_kind.findData(request.body_kind)))
        self._body.setPlainText(request.body)
        self._refresh_curl()

    def token(self) -> str:
        return self._token.text()
