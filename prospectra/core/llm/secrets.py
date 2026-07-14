# 2026-07-13 (P4): API keys live in the OS keychain (Keychain on macOS, Credential Manager on
# Windows, Secret Service on Linux) — never in the project file, never in a dotfile, never in the
# repo. The project store holds only a reference saying "this connection's key is in the keyring".

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SERVICE = "prospectra"


class SecretsError(Exception):
    """The OS keychain refused or is unavailable."""


def set_api_key(provider: str, key: str) -> None:
    import keyring

    try:
        keyring.set_password(SERVICE, provider, key)
    except Exception as exc:  # keyring raises backend-specific errors
        raise SecretsError(f"Could not save the key to the OS keychain: {exc}") from exc
    logger.info("Stored API key for %s in the OS keychain", provider)


def get_api_key(provider: str) -> str | None:
    import keyring

    try:
        return keyring.get_password(SERVICE, provider)
    except Exception as exc:
        raise SecretsError(f"Could not read the key from the OS keychain: {exc}") from exc


def delete_api_key(provider: str) -> None:
    import keyring

    try:
        keyring.delete_password(SERVICE, provider)
    except keyring.errors.PasswordDeleteError:
        pass  # nothing stored — deleting is idempotent
    except Exception as exc:
        raise SecretsError(f"Could not delete the key from the OS keychain: {exc}") from exc
