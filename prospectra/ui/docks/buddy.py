# 2026-07-14 (P4): The Data Buddy chat dock — now real.
# 2026-07-13 (P0): original placeholder.
#
# The privacy badge is always visible and always tells the truth about what this conversation can
# see. The tool trail under each answer shows what the assistant actually looked at, so an answer
# is never a black box — you can see it ran an aggregate rather than making a number up.

from __future__ import annotations

import html
import logging

from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from prospectra.core.catalog import Catalog
from prospectra.core.llm import (
    AuditLog,
    BuddyReply,
    DataBuddy,
    LLMError,
    PrivacyLevel,
    ToolBox,
    make_provider,
)
from prospectra.core.llm import secrets as secret_store
from prospectra.core.llm.sandbox import QuerySandbox
from prospectra.core.mining import Finding
from prospectra.ui.dialogs.settings import BuddySettingsDialog
from prospectra.ui.settings_store import load as load_settings
from prospectra.ui.workers import run_in_pool

logger = logging.getLogger(__name__)

_BADGE = {
    PrivacyLevel.SCHEMA_ONLY: "#008300",  # reserved status green — the most private setting
    PrivacyLevel.AGGREGATES: "#2a78d6",
    PrivacyLevel.SAMPLE_ROWS: "#eda100",  # amber: rows can leave the machine at this level
}


class BuddyDock(QDockWidget):
    def __init__(self, catalog: Catalog) -> None:
        super().__init__("Data Buddy")
        self.setObjectName("dock_buddy")
        self._catalog = catalog
        self._findings: list[Finding] = []
        self._buddy: DataBuddy | None = None
        self._sandbox: QuerySandbox | None = None
        self.audit = AuditLog()

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(6, 6, 6, 6)

        header = QHBoxLayout()
        self._badge = QLabel()
        self._badge.setWordWrap(True)
        header.addWidget(self._badge, 1)
        settings_button = QPushButton("Settings…")
        settings_button.clicked.connect(self.open_settings)
        header.addWidget(settings_button)
        layout.addLayout(header)

        self._transcript = QTextBrowser()
        self._transcript.setOpenExternalLinks(True)
        layout.addWidget(self._transcript, 1)

        row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Ask about your data…")
        self._input.returnPressed.connect(self._send)
        self._send_button = QPushButton("Ask")
        self._send_button.clicked.connect(self._send)
        row.addWidget(self._input, 1)
        row.addWidget(self._send_button)
        layout.addLayout(row)

        self.setWidget(body)
        self.refresh_badge()
        self._say(
            "system",
            "Open a dataset, then ask me about it. I answer by querying your data through "
            "tools — I never see more than the sharing level below allows.",
        )

    # -- state ---------------------------------------------------------------------------------

    def set_findings(self, findings: list[Finding]) -> None:
        """The Analyze tab hands its scan results over so the assistant can discuss them."""
        self._findings = findings
        self._buddy = None  # rebuild the session with the new findings on the next question

    def refresh_badge(self) -> None:
        settings = load_settings()
        colour = _BADGE[settings.privacy]
        self._badge.setText(
            f"<b style='color:{colour}'>{html.escape(settings.privacy.label)}</b><br>"
            f"<span style='font-size:11px'>{html.escape(settings.privacy.explanation)}</span>"
        )
        self._buddy = None  # settings changed → new session

    def open_settings(self) -> None:
        if BuddySettingsDialog(self).exec():
            self.refresh_badge()
            self._say("system", "Settings updated.")

    # -- session -------------------------------------------------------------------------------

    def _ensure_session(self) -> DataBuddy:
        if self._buddy is not None:
            return self._buddy
        if not self._catalog.datasets:
            raise LLMError("Open a dataset first (Sources ▸ Open File…).")

        settings = load_settings()
        key = None
        try:
            key = secret_store.get_api_key(settings.provider)
        except secret_store.SecretsError as exc:
            logger.warning("Keychain unavailable: %s", exc)

        provider = make_provider(
            settings.provider,
            api_key=key,
            model=settings.model or None,
            base_url=settings.base_url or None,
            audit=self.audit,
        )
        if self._sandbox is not None:
            self._sandbox.close()
        self._sandbox = QuerySandbox(self._catalog, list(self._catalog.datasets))
        tools = ToolBox(self._sandbox, settings.privacy, self._findings)
        self._buddy = DataBuddy(provider, tools, settings.privacy)
        return self._buddy

    # -- conversation ---------------------------------------------------------------------------

    def _send(self) -> None:
        question = self._input.text().strip()
        if not question:
            return
        self._input.clear()
        self._say("you", question)
        self._set_busy(True)

        def ask() -> BuddyReply:
            return self._ensure_session().ask(question)

        run_in_pool(
            ask,
            on_result=self._answered,
            on_error=self._failed,
            on_finished=lambda: self._set_busy(False),
        )

    def _answered(self, reply: BuddyReply) -> None:
        body = html.escape(reply.text).replace("\n", "<br>")
        if reply.citations:
            links = "<br>".join(
                f"&nbsp;&nbsp;<a href='{html.escape(c.url)}'>{html.escape(c.title)}</a>"
                for c in reply.citations
            )
            body += f"<br><br><i>Sources:</i><br>{links}"
        if reply.tool_trail:
            looked = html.escape(", ".join(reply.tool_trail))
            body += f"<br><br><span style='font-size:11px;opacity:0.7'>Looked at: {looked}</span>"
        self._say("buddy", body, escaped=True)

    def _failed(self, message: str) -> None:
        self._say("system", f"Could not answer: {html.escape(message)}", escaped=True)
        if "API key" in message:
            QMessageBox.information(
                self,
                "No API key",
                "Add a provider key in the Data Buddy settings, or choose Ollama to run a model "
                "locally with no data leaving this machine.",
            )

    def _set_busy(self, busy: bool) -> None:
        self._send_button.setEnabled(not busy)
        self._input.setEnabled(not busy)
        if busy:
            self._say("system", "Thinking…")

    def _say(self, who: str, text: str, escaped: bool = False) -> None:
        body = text if escaped else html.escape(text).replace("\n", "<br>")
        prefix = {
            "you": "<b>You</b>",
            "buddy": "<b style='color:#2a78d6'>Buddy</b>",
            "system": "<i style='opacity:0.7'>Prospectra</i>",
        }[who]
        self._transcript.append(f"{prefix}<br>{body}<br>")
        scrollbar = self._transcript.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event) -> None:
        if self._sandbox is not None:
            self._sandbox.close()
            self._sandbox = None
        super().closeEvent(event)

    def shutdown(self) -> None:
        if self._sandbox is not None:
            self._sandbox.close()
            self._sandbox = None
