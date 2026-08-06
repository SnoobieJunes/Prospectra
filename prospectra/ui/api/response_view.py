# 2026-07-31 (P7): The response half of the playground. A status pill that tells the truth about
# what happened (including "nothing came back"), the timing and size, and four ways to read the
# body: pretty JSON, raw text, headers (credentials masked), and — when the body is an array of
# flat objects — a real table through the same virtualized DuckTableModel the Data grid uses.

from __future__ import annotations

import json
from typing import Any

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from prospectra.core.connectors.rest.flatten import infer_records_path
from prospectra.core.connectors.rest.paths import records_at
from prospectra.core.http import HttpResponse, redact_headers
from prospectra.ui.data.grid_model import DuckTableModel

_PILL_COLOURS = {2: "#2e7d32", 3: "#1565c0", 4: "#e65100", 5: "#b71c1c"}


def tabular_records(body: Any) -> tuple[list[str], list[tuple[Any, ...]]]:
    """(columns, rows) when the body holds an array of flat objects; ([], []) otherwise."""
    records = records_at(body, infer_records_path(body))
    if len(records) < 2 or not all(isinstance(r, dict) for r in records):
        return [], []
    columns: list[str] = []
    for record in records[:50]:
        for key, value in record.items():
            if key not in columns and (
                value is None or isinstance(value, str | int | float | bool)
            ):
                columns.append(str(key))
    if not columns:
        return [], []
    rows = [tuple(record.get(c) for c in columns) for record in records]
    return columns, rows


class ResponseView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        status_row = QHBoxLayout()
        self._pill = QLabel("—")
        self._pill.setObjectName("status_pill")
        self._meta = QLabel("")
        self._meta.setEnabled(False)
        status_row.addWidget(self._pill)
        status_row.addWidget(self._meta, 1)
        layout.addLayout(status_row)

        self._tabs = QTabWidget()
        self._pretty = QPlainTextEdit()
        self._pretty.setReadOnly(True)
        self._raw = QPlainTextEdit()
        self._raw.setReadOnly(True)
        self._headers = QPlainTextEdit()
        self._headers.setReadOnly(True)
        self._table = QTableView()
        self._tabs.addTab(self._pretty, "Pretty")
        self._tabs.addTab(self._raw, "Raw")
        self._tabs.addTab(self._headers, "Headers")
        self._table_index = self._tabs.addTab(self._table, "Table")
        self._tabs.setTabEnabled(self._table_index, False)
        layout.addWidget(self._tabs, 1)

    def show_response(self, response: HttpResponse) -> None:
        if response.error:
            self._set_pill("FAILED", "#616161")
            self._meta.setText(response.error)
        else:
            colour = _PILL_COLOURS.get(response.status // 100, "#616161")
            self._set_pill(f"{response.status} {response.reason}", colour)
            self._meta.setText(f"{response.elapsed_ms:,.0f} ms · {response.size_bytes:,} bytes")

        if response.json is not None:
            self._pretty.setPlainText(json.dumps(response.json, indent=2, ensure_ascii=False))
        else:
            self._pretty.setPlainText(response.text or response.error)
        self._raw.setPlainText(response.text)
        self._headers.setPlainText(
            "\n".join(f"{k}: {v}" for k, v in redact_headers(response.headers).items())
        )

        columns, rows = tabular_records(response.json)
        if columns:

            def fetch_page(offset: int, limit: int, _rows: list = rows) -> list:
                return _rows[offset : offset + limit]

            model = DuckTableModel([(name, "") for name in columns], len(rows), fetch_page)
            self._table.setModel(model)
            self._tabs.setTabEnabled(self._table_index, True)
        else:
            self._table.setModel(None)
            self._tabs.setTabEnabled(self._table_index, False)
            if self._tabs.currentIndex() == self._table_index:
                self._tabs.setCurrentIndex(0)

    def _set_pill(self, text: str, colour: str) -> None:
        self._pill.setText(text)
        self._pill.setStyleSheet(
            f"#status_pill {{ background: {colour}; color: white; border-radius: 8px; "
            f"padding: 2px 10px; font-weight: 600; }}"
        )
