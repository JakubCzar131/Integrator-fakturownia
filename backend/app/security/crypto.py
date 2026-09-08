"""Symmetric encryption for integration secrets stored in the database.

Design contract
===============
Access tokens for external systems (Fakturownia, SkyShop) are configured in
the application UI and therefore have to be persisted.  They are stored
**encrypted with Fernet** (AES-128-CBC + HMAC-SHA256), so a database dump
alone is worthless: the key material never lives in the database.

Key resolution order:

1. ``INTEGRATION_MASTER_KEY`` — a urlsafe base64 32-byte Fernet key
   (``python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"``).
2. Fallback: a key derived from ``SECRET_KEY`` via HKDF-SHA256.  This keeps
   the installation working out of the box, and ``SECRET_KEY`` is itself an
   env-only secret, so the security level is not lowered.  Rotating
   ``SECRET_KEY`` without setting ``INTEGRATION_MASTER_KEY`` invalidates
   stored secrets — they then have to be re-entered in the UI.

Plaintext secrets are never returned by the API and never logged: everything
that leaves this module towards the outside world is a
:func:`secret_hint` (last four characters).
"""
from __future__ import annotations

import base64
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import get_settings

logger = logging.getLogger(__name__)

HINT_PREFIX = "\u2022" * 4  # ••••


class SecretDecryptionError(RuntimeError):
    """Raised when a stored secret cannot be decrypted with the current key."""


def _derive_key_from_secret_key(secret_key: str) -> bytes:
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"integration-accounts-v1",
        info=b"fernet-master-key",
    ).derive(secret_key.encode("utf-8"))
    return base64.urlsafe_b64encode(derived)


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    configured = settings.integration_master_key.get_secret_value().strip()
    if configured:
        try:
            return Fernet(configured.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                "INTEGRATION_MASTER_KEY is not a valid Fernet key (expected urlsafe "
                "base64 of 32 bytes)"
            ) from exc
    logger.warning(
        "INTEGRATION_MASTER_KEY is not set — deriving the integration encryption key "
        "from SECRET_KEY. Set INTEGRATION_MASTER_KEY in production."
    )
    return Fernet(_derive_key_from_secret_key(settings.secret_key.get_secret_value()))


def reset_key_cache() -> None:
    """Drop the cached key (used by tests and after a settings reload)."""
    _fernet.cache_clear()


def encrypt_secret(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_secret(token: bytes | None) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(bytes(token)).decode("utf-8")
    except InvalidToken as exc:
        raise SecretDecryptionError(
            "Nie udało się odszyfrować zapisanego sekretu — czy zmienił się "
            "INTEGRATION_MASTER_KEY / SECRET_KEY? Wprowadź sekret ponownie."
        ) from exc


def secret_hint(plaintext: str) -> str | None:
    """Short, non-reversible identifier of a secret for display in the UI."""
    if not plaintext:
        return None
    return f"{HINT_PREFIX}{plaintext[-4:]}" if len(plaintext) >= 4 else HINT_PREFIX
