"""Logging setup with mandatory secret masking.

Every log record passes through :class:`SecretMaskingFilter`, which replaces
any occurrence of a configured secret (Fakturownia API token, SkyShop WebAPI
key, JWT secret, bootstrap password) with ``***MASKED***``.  It also masks
``api_token=...`` query-string patterns as defence in depth, so even
accidentally logged URLs never leak credentials.

Secrets configured in the application (and therefore unknown at import time)
register themselves through :func:`register_secret` when their configuration
is loaded, so database-held tokens are masked exactly like env-held ones.
"""
from __future__ import annotations

import logging
import re
import threading

from app.config import get_settings

MASK = "***MASKED***"
_API_TOKEN_PATTERN = re.compile(r"(api_token=)([^&\s\"']+)", re.IGNORECASE)
_AUTH_HEADER_PATTERN = re.compile(r"(Authorization[\"']?\s*[:=]\s*[\"']?)(\S+)", re.IGNORECASE)
_API_KEY_PATTERN = re.compile(r"((?:api[-_]?key|webapi[-_]?key)[\"']?\s*[:=]\s*[\"']?)([^&\s\"',}]+)",
                              re.IGNORECASE)

_dynamic_secrets: set[str] = set()
_dynamic_lock = threading.Lock()


def register_secret(value: str | None) -> None:
    """Add a runtime-configured secret to the masking set."""
    if not value or len(value) < 8:
        return
    with _dynamic_lock:
        _dynamic_secrets.add(value)


def clear_registered_secrets() -> None:
    with _dynamic_lock:
        _dynamic_secrets.clear()


def mask_secrets(text: str) -> str:
    """Mask configured secrets and token-like patterns in arbitrary text."""
    if not text:
        return text
    masked = text
    with _dynamic_lock:
        dynamic = tuple(_dynamic_secrets)
    for secret in (*get_settings().secret_values(), *dynamic):
        if secret in masked:
            masked = masked.replace(secret, MASK)
    masked = _API_TOKEN_PATTERN.sub(rf"\1{MASK}", masked)
    masked = _AUTH_HEADER_PATTERN.sub(rf"\1{MASK}", masked)
    masked = _API_KEY_PATTERN.sub(rf"\1{MASK}", masked)
    return masked


class SecretMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = mask_secrets(str(record.getMessage()))
            record.args = ()
        except Exception:  # pragma: no cover - never break logging
            pass
        return True


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        root.addHandler(handler)
    masking_filter = SecretMaskingFilter()
    for handler in root.handlers:
        handler.addFilter(masking_filter)
    # Also mask uvicorn access logs (they may contain URLs).
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error", "httpx"):
        logging.getLogger(logger_name).addFilter(masking_filter)
