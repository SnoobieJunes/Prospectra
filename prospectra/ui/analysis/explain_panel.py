# 2026-07-14 (P4): "Why might this be?" — the hypothesis panel.
#
# Design rule: the disclaimer is not fine print. It sits above the answer, in the reserved amber
# status colour, with the word "hypotheses" in it — because a plausible-sounding causal story
# attached to a correlation is the most dangerous thing this app could hand someone.

from __future__ import annotations

import html

from PySide6.QtWidgets import QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from prospectra.core.explain import Hypotheses, explain_finding
from prospectra.core.llm import make_provider
from prospectra.core.llm import secrets as secret_store
from prospectra.core.mining import Finding
from prospectra.ui.settings_store import load as load_settings
from prospectra.ui.workers import run_in_pool

CAUTION = "#eda100"  # reserved status colour — always paired with words, never colour alone


class ExplainPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._finding: Finding | None = None
        self._dataset = "your data"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._button = QPushButton("Why might this be? (asks your LLM, searches the web)")
        self._button.clicked.connect(self._run)
        self._button.setEnabled(False)
        layout.addWidget(self._button)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setEnabled(False)
        layout.addWidget(self._status)

        self._view = QTextBrowser()
        self._view.setOpenExternalLinks(True)
        self._view.setVisible(False)
        layout.addWidget(self._view, 1)

    def set_finding(self, finding: Finding | None, dataset_name: str = "your data") -> None:
        self._finding = finding
        self._dataset = dataset_name
        self._button.setEnabled(finding is not None)
        self._view.setVisible(False)
        self._status.setText("")

    def _run(self) -> None:
        if self._finding is None:
            return
        finding = self._finding
        settings = load_settings()
        try:
            key = secret_store.get_api_key(settings.provider)
        except secret_store.SecretsError:
            key = None

        self._button.setEnabled(False)
        self._status.setText("Asking the model and searching for sources…")

        def work() -> Hypotheses:
            provider = make_provider(
                settings.provider,
                api_key=key,
                model=settings.model or None,
                base_url=settings.base_url or None,
            )
            return explain_finding(provider, finding, dataset_name=self._dataset)

        run_in_pool(
            work,
            on_result=self._show,
            on_error=self._failed,
            on_finished=lambda: self._button.setEnabled(True),
        )

    def _show(self, result: Hypotheses) -> None:
        body = [
            f"<p style='color:{CAUTION}'><b>Hypotheses, not conclusions.</b> "
            f"{html.escape(result.disclaimer)}</p>",
            f"<p>{html.escape(result.text).replace(chr(10), '<br>')}</p>",
        ]
        if result.citations:
            links = "<br>".join(
                f"&nbsp;&nbsp;<a href='{html.escape(c.url)}'>{html.escape(c.title)}</a>"
                for c in result.citations
            )
            body.append(f"<p><i>Sources:</i><br>{links}</p>")
        elif result.searched_web:
            body.append("<p><i>The model returned no sources for this one.</i></p>")
        else:
            body.append(
                "<p><i>This provider has no web search in this build, so nothing below is "
                "cited — treat it as the model's prior knowledge, not evidence.</i></p>"
            )
        self._view.setHtml("".join(body))
        self._view.setVisible(True)
        self._status.setText("")

    def _failed(self, message: str) -> None:
        self._status.setText(f"Could not explain this finding: {message}")
