# 2026-07-13 (P1): Add-database dialog — name + SQLAlchemy URL with a background "Test" button.
# Why URL-first: the generic SQLAlchemy connector is the plan's breadth mechanism; per-dialect
# connection forms come in P6. The dialog is honest about driver extras and experimental status.

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from prospectra.core.connectors.sql_alchemy import SQLAlchemyConnector
from prospectra.ui.workers import run_in_pool

_HINT = (
    "Examples:\n"
    "  sqlite:///C:/data/sales.db\n"
    "  postgresql+psycopg2://user:pass@host:5432/dbname   (uv add psycopg2-binary)\n"
    "  mysql+pymysql://user:pass@host/dbname              (uv add pymysql)\n"
    "  mssql+pyodbc://user:pass@dsn                       (uv add pyodbc)\n"
    "Non-SQLite dialects are 'experimental' until tested against your server."
)


class AddDatabaseDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add database connection")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._name = QLineEdit()
        self._url = QLineEdit()
        self._url.setPlaceholderText("dialect+driver://user:pass@host/db")
        form.addRow("Name", self._name)
        form.addRow("SQLAlchemy URL", self._url)
        layout.addLayout(form)

        hint = QLabel(_HINT)
        hint.setEnabled(False)
        layout.addWidget(hint)

        self._test = QPushButton("Test connection")
        self._test.clicked.connect(self._run_test)
        self._verdict = QLabel("")
        layout.addWidget(self._test)
        layout.addWidget(self._verdict)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok.setEnabled(False)
        self._name.textChanged.connect(self._revalidate)
        self._url.textChanged.connect(self._revalidate)

    def _revalidate(self) -> None:
        self._ok.setEnabled(bool(self._name.text().strip() and self._url.text().strip()))

    def _run_test(self) -> None:
        url = self._url.text().strip()
        if not url:
            return
        self._test.setEnabled(False)
        self._verdict.setText("Testing…")

        def ping() -> None:
            SQLAlchemyConnector(url).test_connection()

        run_in_pool(
            ping,
            on_result=lambda _r: self._verdict.setText("✓ Connection OK"),
            on_error=lambda msg: self._verdict.setText(f"✗ {msg}"),
            on_finished=lambda: self._test.setEnabled(True),
        )

    def values(self) -> tuple[str, str]:
        return self._name.text().strip(), self._url.text().strip()
