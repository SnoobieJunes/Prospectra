# 2026-07-14 (P6): The mapping tool's UI. Paste a URL, press "Fetch sample", and it *shows you the
# response* and proposes the records path and the columns it found. You correct what it guessed.
#
# That order matters: a wizard that asks for a JSONPath before showing you any JSON is asking you to
# guess. Here the guess is the machine's, and the human's job is to correct it.
#
# The token is typed once, stored in the OS keychain under `secret_ref`, and never written to the
# project file — the saved mapping says *which* credential to use, not what it is.

from __future__ import annotations

import json
import logging

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from prospectra.core.connectors.rest import (
    AUTH_KINDS,
    PAGINATION_KINDS,
    Auth,
    Column,
    Pagination,
    RestConnector,
    RestMapping,
    infer_mapping_fields,
)
from prospectra.ui.workers import run_in_pool

logger = logging.getLogger(__name__)


class AddApiDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add an API (REST / OData)")
        self.setMinimumWidth(720)
        self._sample: object | None = None

        layout = QVBoxLayout(self)
        blurb = QLabel(
            "Point Prospectra at a JSON endpoint and it becomes a table. Fetch a sample first — "
            "Prospectra will read the response and propose the rows and columns it finds."
        )
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        form = QFormLayout()
        self._name = QLineEdit("api_table")
        self._url = QLineEdit()
        self._url.setPlaceholderText("https://api.example.com/v1/orders")
        form.addRow("Table name", self._name)
        form.addRow("URL", self._url)

        self._auth_kind = QComboBox()
        for kind in AUTH_KINDS:
            self._auth_kind.addItem(kind, kind)
        self._auth_kind.currentIndexChanged.connect(self._auth_changed)
        self._auth_extra = QLineEdit()
        self._auth_extra.setPlaceholderText("(basic: username/email · header: header name)")
        self._token = QLineEdit()
        self._token.setEchoMode(QLineEdit.EchoMode.Password)
        self._token.setPlaceholderText("stored in your OS keychain, never in the project file")
        form.addRow("Auth", self._auth_kind)
        form.addRow("User / header", self._auth_extra)
        form.addRow("Token / password", self._token)

        self._pagination = QComboBox()
        for kind in PAGINATION_KINDS:
            self._pagination.addItem(kind, kind)
        self._page_size = QSpinBox()
        self._page_size.setRange(1, 1000)
        self._page_size.setValue(100)
        self._max_pages = QSpinBox()
        self._max_pages.setRange(1, 500)
        self._max_pages.setValue(20)
        pages = QHBoxLayout()
        pages.addWidget(self._pagination, 1)
        pages.addWidget(QLabel("page size"))
        pages.addWidget(self._page_size)
        pages.addWidget(QLabel("max pages"))
        pages.addWidget(self._max_pages)
        form.addRow("Pagination", pages)

        self._records_path = QLineEdit()
        self._records_path.setPlaceholderText("where the rows live, e.g. data.items — blank = root")
        form.addRow("Rows at", self._records_path)
        layout.addLayout(form)

        fetch_row = QHBoxLayout()
        self._fetch = QPushButton("Fetch sample && suggest columns")
        self._fetch.clicked.connect(self._fetch_sample)
        self._verdict = QLabel("")
        self._verdict.setWordWrap(True)
        fetch_row.addWidget(self._fetch)
        fetch_row.addWidget(self._verdict, 1)
        layout.addLayout(fetch_row)

        self._columns = QTableWidget(0, 2)
        self._columns.setHorizontalHeaderLabels(["Column", "Path in each record"])
        self._columns.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(QLabel("Columns (edit or delete any row):"))
        layout.addWidget(self._columns, 1)

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMaximumHeight(120)
        self._preview.setPlaceholderText("The sample response appears here.")
        layout.addWidget(self._preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok.setEnabled(False)
        self._url.textChanged.connect(self._revalidate)
        self._auth_changed()

    # -- state -----------------------------------------------------------------------------------

    def _auth_changed(self) -> None:
        kind = str(self._auth_kind.currentData())
        self._auth_extra.setEnabled(kind in ("basic", "header", "query"))
        self._token.setEnabled(kind != "none")

    def _revalidate(self) -> None:
        self._ok.setEnabled(bool(self._url.text().strip()) and self._columns.rowCount() > 0)

    def mapping(self) -> RestMapping:
        kind = str(self._auth_kind.currentData())
        extra = self._auth_extra.text().strip()
        auth = Auth(
            kind=kind,
            secret_ref=f"api:{self._name.text().strip() or 'api'}",
            user=extra if kind == "basic" else "",
            header=extra if kind == "header" else "",
            param=extra if kind == "query" else "",
        )
        pagination = Pagination(
            kind=str(self._pagination.currentData()),
            page_size=self._page_size.value(),
            max_pages=self._max_pages.value(),
        )
        columns: list[Column] = []
        for row in range(self._columns.rowCount()):
            name_item = self._columns.item(row, 0)
            path_item = self._columns.item(row, 1)
            if name_item is None or path_item is None or not name_item.text().strip():
                continue
            columns.append(Column(name=name_item.text().strip(), path=path_item.text().strip()))
        return RestMapping(
            name=self._name.text().strip() or "api_table",
            url=self._url.text().strip(),
            auth=auth,
            pagination=pagination,
            records_path=self._records_path.text().strip(),
            columns=columns,
        )

    def token(self) -> str:
        return self._token.text()

    # -- the sample --------------------------------------------------------------------------------

    def _fetch_sample(self) -> None:
        try:
            mapping = self.mapping()
            mapping.pagination = Pagination(kind="none")  # one page is a sample
            mapping.validate()
        except ValueError as exc:
            self._verdict.setText(f"✗ {exc}")
            return
        connector = RestConnector(mapping, self.token() or None)
        self._fetch.setEnabled(False)
        self._verdict.setText("Fetching…")
        run_in_pool(
            connector.sample,
            on_result=self._sample_ready,
            on_error=lambda msg: self._verdict.setText(f"✗ {msg}"),
            on_finished=lambda: self._fetch.setEnabled(True),
        )

    def _sample_ready(self, body: object) -> None:
        self._sample = body
        text = json.dumps(body, indent=2, default=str)
        self._preview.setPlainText(text[:4000] + ("\n…" if len(text) > 4000 else ""))

        records_path, columns = infer_mapping_fields(body)
        if not self._records_path.text().strip():
            self._records_path.setText(records_path)
        self._set_columns(columns)
        if columns:
            self._verdict.setText(
                f"✓ Found {len(columns)} column(s) at "
                f"{records_path or '(the response root)'} — correct anything below."
            )
        else:
            self._verdict.setText(
                "✓ Fetched, but no rows were found. Set 'Rows at' to the field holding the list."
            )
        self._revalidate()

    def _set_columns(self, columns: list[Column]) -> None:
        self._columns.setRowCount(len(columns))
        for row, column in enumerate(columns):
            self._columns.setItem(row, 0, QTableWidgetItem(column.name))
            self._columns.setItem(row, 1, QTableWidgetItem(column.path))
