"""Encryption at rest for stored secrets.

The Telegram bot token is a credential: whoever holds it can control the bot
and send messages as the caregiver's assistant. Storing it in plaintext in
SQLite means anyone with the database file can read it.

This module encrypts such values with Fernet (AES-128-CBC + HMAC). The key
comes from ECHEOS_SECRET_KEY; if that is unset we generate one into
app/.secret_key with owner-only permissions, so a fresh install still works
without setup while never leaving a token in plaintext.
"""

from __future__ import annotations

import os
from pathlib import Path

KEY_PATH = Path(__file__).resolve().parent / ".secret_key"
PREFIX = "enc::"


def _load_key() -> bytes:
    env = os.environ.get("ECHEOS_SECRET_KEY", "").strip()
    if env:
        return env.encode()
    if KEY_PATH.exists():
        return KEY_PATH.read_bytes().strip()
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    try:
        os.chmod(KEY_PATH, 0o600)
    except OSError:
        pass
    return key


def _fernet():
    from cryptography.fernet import Fernet
    return Fernet(_load_key())


def encrypt(value: str) -> str:
    if not value:
        return ""
    if value.startswith(PREFIX):
        return value          # already encrypted; never double-wrap
    try:
        return PREFIX + _fernet().encrypt(value.encode()).decode()
    except Exception:
        # If encryption is unavailable, refuse to store plaintext silently.
        raise


def decrypt(value: str) -> str:
    if not value:
        return ""
    if not value.startswith(PREFIX):
        return value          # legacy plaintext row
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except Exception:
        return ""


def is_encrypted(value: str) -> bool:
    return bool(value) and value.startswith(PREFIX)
