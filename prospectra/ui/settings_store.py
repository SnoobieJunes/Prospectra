# 2026-07-14 (P4): Non-secret preferences (provider, model, privacy level, base URL) live in
# QSettings — the OS-native prefs store. The API key does NOT live here: it goes to the OS
# keychain via core.llm.secrets. Keeping the two apart is the point.

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings

from prospectra.core.llm import PrivacyLevel

# Module-level so tests can point them at a throwaway namespace — a test must never be able to
# read or overwrite the developer's real preferences.
_ORG = "Prospectra"
_APP = "Prospectra"


@dataclass(frozen=True)
class BuddySettings:
    provider: str = "anthropic"
    model: str = ""  # empty means "the provider's default"
    base_url: str = ""
    privacy: PrivacyLevel = PrivacyLevel.AGGREGATES  # schema + summaries, never rows


def load() -> BuddySettings:
    settings = QSettings(_ORG, _APP)
    raw_privacy = str(settings.value("buddy/privacy", PrivacyLevel.AGGREGATES.value))
    try:
        privacy = PrivacyLevel(raw_privacy)
    except ValueError:
        privacy = PrivacyLevel.AGGREGATES
    return BuddySettings(
        provider=str(settings.value("buddy/provider", "anthropic")),
        model=str(settings.value("buddy/model", "")),
        base_url=str(settings.value("buddy/base_url", "")),
        privacy=privacy,
    )


def save(value: BuddySettings) -> None:
    settings = QSettings(_ORG, _APP)
    settings.setValue("buddy/provider", value.provider)
    settings.setValue("buddy/model", value.model)
    settings.setValue("buddy/base_url", value.base_url)
    settings.setValue("buddy/privacy", value.privacy.value)
    settings.sync()
