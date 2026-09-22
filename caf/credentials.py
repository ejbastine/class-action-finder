"""Anthropic API key lookup: Windows Credential Manager (via keyring) first, then the
environment / `.env`. Only needed for `run --match`. Values are never printed."""

from __future__ import annotations

import os

SERVICE = "class-action-finder"
NAME = "ANTHROPIC_API_KEY"


def _keyring_get() -> str | None:
    try:
        import keyring
        return keyring.get_password(SERVICE, NAME)
    except Exception:
        return None


def get_api_key() -> str:
    return _keyring_get() or os.environ.get(NAME, "")


def source() -> str:
    if _keyring_get():
        return "Windows Credential Manager"
    if os.environ.get(NAME):
        return "environment / .env"
    return "missing"


def set_api_key(value: str) -> None:
    import keyring
    keyring.set_password(SERVICE, NAME, value)


def delete_api_key() -> bool:
    try:
        import keyring
        keyring.delete_password(SERVICE, NAME)
        return True
    except Exception:
        return False
