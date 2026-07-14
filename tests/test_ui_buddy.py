# 2026-07-14 (P4): Data Buddy UI — the chat dock holds a conversation through a fake provider, the
# privacy badge tells the truth, and the settings dialog stores keys in the keychain (never on
# disk). Offscreen, no network, no keys.

import pytest

from prospectra.core.catalog import Catalog
from prospectra.core.llm import Citation, PrivacyLevel
from prospectra.core.mining import Finding
from prospectra.ui.analysis.explain_panel import ExplainPanel
from prospectra.ui.dialogs.settings import BuddySettingsDialog
from prospectra.ui.docks.buddy import BuddyDock
from prospectra.ui.settings_store import BuddySettings, load, save
from tests.fake_provider import FakeProvider, text_reply, tool_reply


@pytest.fixture(autouse=True)
def isolated_settings(qtbot, tmp_path, monkeypatch, request):
    """Keep QSettings and the keychain out of the developer's real environment.

    A unique application name per test is what actually isolates it: QSettings keeps an in-process
    cache keyed by (org, app), so redirecting the *path* alone still let one test's saved value
    leak into the next test's "default" — which is how this fixture was wrong the first time.
    """
    from PySide6.QtCore import QSettings

    import prospectra.ui.settings_store as store

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "qsettings")
    )
    monkeypatch.setattr(store, "_APP", f"ProspectraTest-{request.node.name}")

    import keyring

    vault: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(keyring, "set_password", lambda s, u, p: vault.__setitem__((s, u), p))
    monkeypatch.setattr(keyring, "get_password", lambda s, u: vault.get((s, u)))
    return vault


@pytest.fixture()
def catalog(tmp_path):
    path = tmp_path / "sales.csv"
    path.write_text("region,amount\nWest,10\nWest,30\nEast,20\n", encoding="utf-8")
    cat = Catalog()
    cat.open_file(path)
    yield cat
    cat.close()


def _wire_fake(dock: BuddyDock, replies) -> FakeProvider:
    """Swap the real provider factory for a scripted one, leaving the rest of the dock intact."""
    provider = FakeProvider(replies, audit=dock.audit)
    import prospectra.ui.docks.buddy as buddy_module

    buddy_module.make_provider = lambda *a, **k: provider  # type: ignore[assignment]
    return provider


def test_chat_answers_a_question_through_the_tools(qtbot, catalog, monkeypatch):
    dock = BuddyDock(catalog)
    qtbot.addWidget(dock)
    provider = _wire_fake(
        dock,
        [
            tool_reply(
                "aggregate",
                {
                    "table": "sales",
                    "group_by": ["region"],
                    "metrics": [{"function": "sum", "column": "amount"}],
                },
            ),
            text_reply("West totals 40; East totals 20."),
        ],
    )

    dock._input.setText("Which region sells more?")
    dock._send()
    qtbot.waitUntil(lambda: "West totals 40" in dock._transcript.toPlainText(), timeout=10_000)

    transcript = dock._transcript.toPlainText()
    assert "Which region sells more?" in transcript
    assert "Looked at: aggregate" in transcript  # the answer shows its working
    assert provider.audit.entries  # and every request was audited


def test_the_badge_states_the_privacy_level(qtbot, catalog):
    save(BuddySettings(provider="anthropic", privacy=PrivacyLevel.SCHEMA_ONLY))
    dock = BuddyDock(catalog)
    qtbot.addWidget(dock)
    dock.refresh_badge()
    assert "Schema only" in dock._badge.text()
    assert "No values of any kind leave this machine" in dock._badge.text()


def test_default_privacy_is_the_safe_one():
    assert load().privacy == PrivacyLevel.AGGREGATES  # summaries, never rows


def test_settings_dialog_stores_the_key_in_the_keychain(qtbot, isolated_settings):
    dialog = BuddySettingsDialog()
    qtbot.addWidget(dialog)
    dialog._provider.setCurrentIndex(dialog._provider.findData("anthropic"))
    dialog._key.setText("sk-secret-value")
    dialog._model.setText("claude-opus-4-8")
    dialog._save()

    # The key went to the keychain…
    assert isolated_settings[("prospectra", "anthropic")] == "sk-secret-value"
    # …and only non-secret preferences went to QSettings.
    settings = load()
    assert settings.provider == "anthropic"
    assert settings.model == "claude-opus-4-8"


def test_settings_dialog_badges_unverified_providers(qtbot):
    dialog = BuddySettingsDialog()
    qtbot.addWidget(dialog)
    labels = [dialog._provider.itemText(i) for i in range(dialog._provider.count())]
    assert any("experimental" in label for label in labels)


def test_explain_panel_shows_hypotheses_with_sources(qtbot, monkeypatch):
    panel = ExplainPanel()
    qtbot.addWidget(panel)
    provider = FakeProvider(
        [
            text_reply(
                "Warm weather plausibly raises demand; school holidays may confound this.",
                citations=[Citation(title="Ice cream seasonality", url="https://example.org/a")],
            )
        ]
    )
    import prospectra.ui.analysis.explain_panel as panel_module

    monkeypatch.setattr(panel_module, "make_provider", lambda *a, **k: provider)

    finding = Finding(
        kind="correlation",
        title="temperature_c ↔ ice_cream_sales",
        headline="When temperature_c goes up, ice_cream_sales tends to rise.",
        columns=["temperature_c", "ice_cream_sales"],
        effect=0.85,
        effect_name="|r|",
        p_value=1e-300,
        q_value=1e-299,
        n=1095,
    )
    panel.set_finding(finding, "ice cream")
    assert panel._button.isEnabled()
    panel._run()
    # isVisible() would be False here regardless — the panel itself is never shown in a headless
    # test — so wait on the content the worker delivered.
    qtbot.waitUntil(lambda: "confound" in panel._view.toPlainText(), timeout=10_000)

    html = panel._view.toHtml()
    assert "Hypotheses, not conclusions" in html  # the warning leads, it does not trail
    assert "confound" in html
    assert "example.org" in html  # the citation is a live link
