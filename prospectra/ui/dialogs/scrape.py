# 2026-07-14 (P5): The scrape dialog. Deliberately plain — a URL and two switches — because the
# interesting behaviour (robots.txt, rate limiting, table extraction) is the engine's, not the
# dialog's. The text says what the tool will and will not do, so nobody has to guess whether it
# respects robots.txt: it does, always, and the copy says so.

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class ScrapeDialog(QDialog):
    def __init__(self, staging: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Scrape a web page")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        blurb = QLabel(
            "Prospectra fetches the page, extracts every data table on it, and saves each one as a "
            "CSV you can open, prep in a flow, and scan.\n\n"
            "It obeys robots.txt and rate-limits itself to one request per second per site. If a "
            "site disallows this page, it will not be fetched."
        )
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        form = QFormLayout()
        self._url = QLineEdit()
        self._url.setPlaceholderText("https://en.wikipedia.org/wiki/List_of_countries_by_GDP…")
        form.addRow("Page URL", self._url)
        self._staging = QLabel(str(staging))
        self._staging.setWordWrap(True)
        self._staging.setEnabled(False)
        form.addRow("Save CSVs to", self._staging)
        self._max_tables = QSpinBox()
        self._max_tables.setRange(1, 50)
        self._max_tables.setValue(10)
        form.addRow("Keep at most", self._max_tables)
        self._tables_only = QCheckBox("Tables only (fail if the page has none)")
        self._tables_only.setChecked(True)
        form.addRow("", self._tables_only)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, bool, int]:
        return self._url.text().strip(), self._tables_only.isChecked(), self._max_tables.value()
