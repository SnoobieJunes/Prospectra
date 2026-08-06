# 2026-07-31 (P7): The API playground workspace — explore an unfamiliar endpoint before committing
# to anything. Type a request, send it off the GUI thread, read the response four ways, then either
# save the request (replayable later, `prospectra api-send` included) or promote it to a data
# source, which hands a RestMapping to the exact catalog path "Add API…" already uses.
#
# Secrets: the token box is used for this send and offered to the keychain on save; placeholders
# (`{{secret:<ref>}}`) resolve from the keychain inside the worker. The saved documents only ever
# carry references.

from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from prospectra.core.connectors.rest import RestMapping, infer_mapping_fields
from prospectra.core.connectors.rest.mapping import Pagination
from prospectra.core.http import HttpRequest, HttpResponse, resolve_placeholders, send
from prospectra.core.llm import secrets as secret_store
from prospectra.ui.api.request_editor import RequestEditor
from prospectra.ui.api.response_view import ResponseView
from prospectra.ui.workers import run_in_pool

logger = logging.getLogger(__name__)


def _send_with_keychain(request: HttpRequest, token: str) -> HttpResponse:
    """Worker-thread body: resolve credentials, then send. Never touches a widget."""

    def resolver(ref: str) -> str:
        secret = secret_store.get_api_key(ref)
        if not secret:
            raise ValueError(f"no keychain entry named {ref!r} — save the credential first")
        return secret

    secret = token or None
    if request.auth.kind != "none" and not secret and request.auth.secret_ref:
        secret = secret_store.get_api_key(request.auth.secret_ref)
    resolved = resolve_placeholders(request, resolver)
    return send(resolved, secret)


class ApiPlaygroundTab(QWidget):
    """The playground workspace. The main window owns all project-store work; we emit signals."""

    request_save_requested = Signal(object)  # HttpRequest
    source_save_requested = Signal(object, str)  # RestMapping, token

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self._send = QPushButton("Send")
        self._send.setDefault(True)
        self._send.clicked.connect(self._send_clicked)
        self._save_request = QPushButton("Save Request…")
        self._save_request.clicked.connect(self._save_request_clicked)
        self._save_source = QPushButton("Save as Data Source…")
        self._save_source.setToolTip(
            "Turn this request into a reusable API table (send it once first, so Prospectra "
            "can see where the rows live)."
        )
        self._save_source.clicked.connect(self._save_source_clicked)
        self._saved = QComboBox()
        self._saved.setPlaceholderText("Saved requests…")
        self._saved.activated.connect(self._load_saved)
        self._status = QLabel("")
        toolbar.addWidget(self._send)
        toolbar.addWidget(self._save_request)
        toolbar.addWidget(self._save_source)
        toolbar.addWidget(self._saved, 1)
        toolbar.addWidget(self._status, 2)
        layout.addLayout(toolbar)

        splitter = QSplitter()
        self._editor = RequestEditor()
        self._response = ResponseView()
        splitter.addWidget(self._editor)
        splitter.addWidget(self._response)
        splitter.setSizes([420, 560])
        layout.addWidget(splitter, 1)

        self._last_body: object | None = None
        self._last_body_url: str = ""
        self._saved_requests: list[tuple[str, str, HttpRequest]] = []
        # 2026-08-05: editing the request drops the previous response. Without this, changing the
        # URL and pressing "Save as Data Source" built a mapping whose columns were inferred from
        # a DIFFERENT endpoint's body — a saved "table" that describes something it never saw.
        self._editor.changed.connect(self._request_edited)

    # -- sending ---------------------------------------------------------------------------------

    def _send_clicked(self) -> None:
        try:
            request = self._editor.request()
            request.validate()
        except ValueError as exc:
            self._status.setText(f"✗ {exc}")
            return
        self._send.setEnabled(False)
        self._status.setText(f"Sending {request.method} {request.url}…")
        run_in_pool(
            _send_with_keychain,
            request,
            self._editor.token(),
            on_result=self._response_ready,
            on_error=lambda msg: self._status.setText(f"✗ {msg}"),
            on_finished=lambda: self._send.setEnabled(True),
        )

    def _request_edited(self) -> None:
        """Any edit invalidates the last response — it described the request as it was."""
        if self._last_body is not None and self._editor.request().url != self._last_body_url:
            self._last_body = None
            self._status.setText("Request changed — send it again before saving it as a source.")

    def _response_ready(self, response: HttpResponse) -> None:
        self._response.show_response(response)
        self._last_body = response.json
        self._last_body_url = self._editor.request().url
        if response.error:
            self._status.setText("✗ the request did not complete — see the response pane")
        else:
            self._status.setText("")

    # -- saving ----------------------------------------------------------------------------------

    def _save_request_clicked(self) -> None:
        try:
            request = self._editor.request()
            request.validate()
        except ValueError as exc:
            self._status.setText(f"✗ {exc}")
            return
        self.request_save_requested.emit(request)

    def _save_source_clicked(self) -> None:
        try:
            mapping = self.mapping()
        except ValueError as exc:
            self._status.setText(f"✗ {exc}")
            return
        self.source_save_requested.emit(mapping, self._editor.token())

    def mapping(self) -> RestMapping:
        """This request as a RestMapping, rows/columns inferred from the last response."""
        request = self._editor.request()
        request.validate()
        if self._last_body is None:
            raise ValueError(
                "send the request once first — Prospectra reads the response to find the rows"
            )
        records_path, columns = infer_mapping_fields(self._last_body)
        if not columns:
            raise ValueError(
                "no rows were found in the last response — this endpoint may not return a table"
            )
        return RestMapping(
            url=request.url,
            method=request.method,
            headers=dict(request.headers),
            params=dict(request.params),
            body_kind=request.body_kind,
            body=request.body,
            auth=request.auth,
            pagination=Pagination(kind="none"),  # the playground saw one page; honest default
            records_path=records_path,
            columns=columns,
        )

    # -- saved requests --------------------------------------------------------------------------

    def set_saved_requests(self, records: list[tuple[str, str, HttpRequest]]) -> None:
        """(record id, name, request) triples from the open project."""
        self._saved_requests = list(records)
        self._saved.clear()
        for _record_id, name, _request in self._saved_requests:
            self._saved.addItem(name)
        self._saved.setCurrentIndex(-1)

    def _load_saved(self, index: int) -> None:
        if 0 <= index < len(self._saved_requests):
            _record_id, name, request = self._saved_requests[index]
            self._editor.set_request(request)
            self._status.setText(f"Loaded “{name}”")

    def show_status(self, message: str) -> None:
        self._status.setText(message)
