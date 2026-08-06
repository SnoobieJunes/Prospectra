# 2026-07-14 (P4): Data Buddy settings — pick a provider, store its key in the OS keychain, and
# choose how much of your data the assistant is allowed to see.
#
# The privacy control is the most important widget in this app, so it is not buried: the level is
# a plain-language radio choice with its consequences spelled out underneath, and the default is
# the safe one (summaries, never rows).

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from prospectra.core.llm import PROVIDERS, Message, PrivacyLevel, make_provider
from prospectra.core.llm import secrets as secret_store
from prospectra.ui.settings_store import BuddySettings, load, save
from prospectra.ui.workers import run_in_pool


class BuddySettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Data Buddy settings")
        self.setMinimumWidth(560)
        self._current = load()

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_provider_box())
        layout.addWidget(self._build_privacy_box())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._provider_changed()

    # -- provider ---------------------------------------------------------------------------

    def _build_provider_box(self) -> QGroupBox:
        box = QGroupBox("Provider")
        form = QFormLayout(box)

        self._provider = QComboBox()
        for type_name, cls in PROVIDERS.items():
            label = cls.display_name
            if not cls.verified:
                # Honest badge: the request shape is implemented but no live call was made here.
                label += "  (experimental)"
            self._provider.addItem(label, type_name)
        index = self._provider.findData(self._current.provider)
        if index >= 0:
            self._provider.setCurrentIndex(index)
        self._provider.currentIndexChanged.connect(self._provider_changed)
        form.addRow("Provider", self._provider)

        self._model = QLineEdit(self._current.model)
        self._model.setToolTip("Editable — whatever model id your endpoint serves.")
        form.addRow("Model", self._model)

        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.setPlaceholderText("stored in your OS keychain, never in the project file")
        form.addRow("API key", self._key)

        self._base_url = QLineEdit(self._current.base_url)
        self._base_url.setToolTip(
            "Editable — point this at any OpenAI-compatible endpoint (your own gateway, a "
            "self-hosted server). No code change needed."
        )
        form.addRow("Base URL", self._base_url)

        self._test = QPushButton("Test connection")
        self._test.clicked.connect(self._run_test)
        form.addRow(self._test)
        self._verdict = QLabel("")
        self._verdict.setWordWrap(True)
        form.addRow(self._verdict)
        return box

    def _provider_changed(self) -> None:
        cls = PROVIDERS[self._provider.currentData()]
        self._model.setPlaceholderText(cls.default_model or "required — the endpoint's model id")
        self._key.setEnabled(cls.needs_api_key)
        # 2026-07-14 (P6): driven by the provider's declared capability, not by its name, so a new
        # OpenAI-compatible provider (Muse Spark) needs no edit here.
        # 2026-08-05: driven by the provider's declared default, never by its name — the P6
        # `if cls.type_name == "muse_spark"` special case broke the project's own
        # "a descriptor drives the form" rule and had to be edited for every new endpoint.
        # The field is prefilled (not just hinted) so the endpoint is visibly editable: swap it
        # for your own OpenAI-compatible gateway without touching code.
        self._base_url.setEnabled(cls.supports_custom_endpoint)
        self._base_url.setPlaceholderText(
            cls.default_base_url or "the endpoint's OpenAI-compatible root"
        )
        if cls.supports_custom_endpoint and not self._base_url.text().strip():
            self._base_url.setText(cls.default_base_url)
        existing = _safe_get_key(cls.type_name)
        self._key.setText(existing or "")
        local_note = "" if cls.needs_api_key else "Runs locally — no data leaves this machine."
        note = cls.setup_hint or local_note
        if not cls.verified:
            note += (
                "  Experimental: the request format is implemented but has not been run against "
                "this provider's live API in this build."
            )
        self._verdict.setText(note.strip())

    def _run_test(self) -> None:
        self._test.setEnabled(False)
        self._verdict.setText("Testing…")
        provider_type = self._provider.currentData()
        key = self._key.text().strip() or None
        model = self._model.text().strip() or None
        base_url = self._base_url.text().strip() or None

        def ping() -> str:
            provider = make_provider(provider_type, api_key=key, model=model, base_url=base_url)
            reply = provider.complete(
                "Reply with the single word OK.",
                [Message(role="user", text="Are you there?")],
            )
            return reply.text.strip()[:80]

        run_in_pool(
            ping,
            on_result=lambda text: self._verdict.setText(f"✓ Reachable — replied: {text!r}"),
            on_error=lambda msg: self._verdict.setText(f"✗ {msg}"),
            on_finished=lambda: self._test.setEnabled(True),
        )

    # -- privacy -----------------------------------------------------------------------------

    def _build_privacy_box(self) -> QGroupBox:
        box = QGroupBox("What the assistant may see")
        layout = QVBoxLayout(box)
        self._privacy_group = QButtonGroup(self)
        for level in PrivacyLevel:
            radio = QRadioButton(level.label)
            radio.setChecked(level == self._current.privacy)
            self._privacy_group.addButton(radio)
            radio.setProperty("level", level.value)
            layout.addWidget(radio)
            detail = QLabel(level.explanation)
            detail.setWordWrap(True)
            detail.setEnabled(False)
            detail.setContentsMargins(22, 0, 0, 6)
            layout.addWidget(detail)
        note = QLabel(
            "Every request is logged locally — open the Log dock to read exactly what was sent."
        )
        note.setWordWrap(True)
        note.setEnabled(False)
        layout.addWidget(note)
        return box

    def _selected_privacy(self) -> PrivacyLevel:
        button = self._privacy_group.checkedButton()
        if button is None:
            return PrivacyLevel.AGGREGATES
        return PrivacyLevel(str(button.property("level")))

    # -- persistence ---------------------------------------------------------------------------

    def _save(self) -> None:
        provider_type = self._provider.currentData()
        key = self._key.text().strip()
        if key:
            try:
                secret_store.set_api_key(provider_type, key)
            except secret_store.SecretsError as exc:
                QMessageBox.warning(self, "Could not save the key", str(exc))
                return
        save(
            BuddySettings(
                provider=provider_type,
                model=self._model.text().strip(),
                base_url=self._base_url.text().strip(),
                privacy=self._selected_privacy(),
            )
        )
        self.accept()


def _safe_get_key(provider: str) -> str | None:
    try:
        return secret_store.get_api_key(provider)
    except secret_store.SecretsError:
        return None  # no keychain available (headless CI) — the user can still type one in
