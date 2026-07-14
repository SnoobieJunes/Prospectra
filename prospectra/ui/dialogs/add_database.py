# 2026-07-14 (P6): The dialog is now generated from a dialect descriptor, not hand-written per
# database. Pick "Snowflake" and you get Snowflake's fields; the URL is built (and URL-quoted) for
# you. "Advanced" still takes a raw SQLAlchemy URL, because the generic path must never be taken
# away — a dialect nobody wrote a descriptor for is still connectable by URL today.
#
# Three honesty affordances, none decorative:
#   * the driver's absence is detected before you try, with the exact command to install it — the
#     alternative is a SQLAlchemy ImportError in a message box;
#   * the experimental badge is on the dialect, and says *why* (untested against a real server);
#   * passwords are typed into a masked field, kept out of the project file, and stored in the OS
#     keychain (the URL that lands in the project has its password removed).
# 2026-07-13 (P1): original URL-only dialog.

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from prospectra.core.connectors.dialects import DIALECTS, Dialect
from prospectra.core.connectors.sql_alchemy import SQLAlchemyConnector
from prospectra.ui.workers import run_in_pool

_ADVANCED_HINT = (
    "Any SQLAlchemy URL works here, including dialects with no form above:\n"
    "  postgresql+psycopg://user:pass@host:5432/db\n"
    "  duckdb:///C:/data/warehouse.duckdb"
)


class AddDatabaseDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add database connection")
        self.setMinimumWidth(560)
        self._fields: dict[str, QLineEdit] = {}

        layout = QVBoxLayout(self)

        top = QFormLayout()
        self._name = QLineEdit()
        self._name.setPlaceholderText("A name for this connection")
        self._dialect = QComboBox()
        for dialect in DIALECTS:
            self._dialect.addItem(dialect.display_name, dialect.key)
        self._dialect.currentIndexChanged.connect(self._dialect_changed)
        top.addRow("Name", self._name)
        top.addRow("Database", self._dialect)
        layout.addLayout(top)

        self._badge = QLabel()
        self._badge.setWordWrap(True)
        layout.addWidget(self._badge)

        self._form_box = QGroupBox("Connection")
        self._form = QFormLayout(self._form_box)
        layout.addWidget(self._form_box)

        self._advanced = QCheckBox("Enter a SQLAlchemy URL myself (advanced)")
        self._advanced.stateChanged.connect(self._advanced_toggled)
        layout.addWidget(self._advanced)
        self._url = QLineEdit()
        self._url.setPlaceholderText("dialect+driver://user:pass@host/db")
        self._url.setVisible(False)
        self._url.textChanged.connect(self._revalidate)
        self._url_hint = QLabel(_ADVANCED_HINT)
        self._url_hint.setEnabled(False)
        self._url_hint.setVisible(False)
        layout.addWidget(self._url)
        layout.addWidget(self._url_hint)

        self._test = QPushButton("Test connection")
        self._test.clicked.connect(self._run_test)
        self._verdict = QLabel("")
        self._verdict.setWordWrap(True)
        layout.addWidget(self._test)
        layout.addWidget(self._verdict)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)

        self._name.textChanged.connect(self._revalidate)
        self._dialect_changed()

    # -- dialect form ------------------------------------------------------------------------

    @property
    def dialect(self) -> Dialect:
        from prospectra.core.connectors.dialects import DIALECTS_BY_KEY

        return DIALECTS_BY_KEY[str(self._dialect.currentData())]

    def _dialect_changed(self) -> None:
        dialect = self.dialect
        while self._form.count():
            item = self._form.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self._fields.clear()

        for field in dialect.fields:
            editor = QLineEdit(field.default)
            if field.secret:
                editor.setEchoMode(QLineEdit.EchoMode.Password)
            if field.help:
                editor.setPlaceholderText(field.help)
            editor.textChanged.connect(self._revalidate)
            label = field.label if field.required else f"{field.label} (optional)"
            self._form.addRow(label, editor)
            self._fields[field.name] = editor

        self._badge.setText(self._badge_text(dialect))
        self._revalidate()

    def _badge_text(self, dialect: Dialect) -> str:
        parts: list[str] = []
        if dialect.status == "verified":
            parts.append("<b style='color:#008300'>verified</b> — exercised by this repo's tests.")
        else:
            parts.append(
                "<b style='color:#eda100'>experimental</b> — implemented but never run against a "
                "real server from this build."
            )
        if not dialect.driver_installed:
            parts.append(
                f"<br><b>Driver not installed.</b> Run <code>{dialect.install_hint()}</code>, then "
                "restart Prospectra."
            )
        if dialect.notes:
            parts.append(f"<br><span style='font-size:11px'>{dialect.notes}</span>")
        return "".join(parts)

    def _advanced_toggled(self) -> None:
        raw = self._advanced.isChecked()
        self._form_box.setVisible(not raw)
        self._url.setVisible(raw)
        self._url_hint.setVisible(raw)
        self._revalidate()

    # -- values ---------------------------------------------------------------------------------

    def _values(self) -> dict[str, str]:
        return {name: editor.text() for name, editor in self._fields.items()}

    def url(self) -> str:
        """The URL to connect with — including the password (which never reaches the project)."""
        if self._advanced.isChecked():
            return self._url.text().strip()
        return self.dialect.build_url(self._values())

    def secret(self) -> str:
        """The password/token, if this dialect has one. Destined for the OS keychain."""
        for field in self.dialect.fields:
            if field.secret:
                return self._fields[field.name].text()
        return ""

    def values(self) -> tuple[str, str]:
        """(name, url) — the signature the main window has used since P1."""
        return self._name.text().strip(), self.url()

    def _revalidate(self) -> None:
        name = bool(self._name.text().strip())
        try:
            ready = bool(self.url())
        except ValueError:  # a required field is still empty
            ready = False
        self._ok.setEnabled(name and ready)
        self._test.setEnabled(ready)

    # -- test ------------------------------------------------------------------------------------

    def _run_test(self) -> None:
        try:
            url = self.url()
        except ValueError as exc:
            self._verdict.setText(f"✗ {exc}")
            return
        dialect = self.dialect
        if not self._advanced.isChecked() and not dialect.driver_installed:
            self._verdict.setText(
                f"✗ The {dialect.display_name} driver is not installed. Run "
                f"`{dialect.install_hint()}` and restart."
            )
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
