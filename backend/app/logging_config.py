"""Logging setup with mandatory secret masking.

Every log record passes through :class:`SecretMaskingFilter`, which replaces
any occurrence of a configured secret (Fakturownia API token, JWT secret,
bootstrap password) with ``***MASKED***``.  It also masks ``api_token=...``
query-string patterns as defence in depth, so even accidentally logged URLs
never leak credentials.
"""
from __future__ import annotations

import logging
import re

from app.config import get_settings

MASK = "***MASKED***"
_API_TOKEN_PATTERN = re.compile(r"(api_token=)([^&\s\"']+)", re.IGNORECASE)
_AUTH_HEADER_PATTERN = re.compile(r"(Authorization[\"']?\s*[:=]\s*[\"']?)(\S+)", re.IGNORECASE)


def mask_secrets(text: str) -> str:
    """Mask configured secrets and token-like patterns in arbitrary text."""
    if not text:
        return text
    masked = text
    for secret in get_settings().secret_values():
        if secret in masked:
            masked = masked.replace(secret, MASK)
    masked = _API_TOKEN_PATTERN.sub(rf"\1{MASK}", masked)
    masked = _AUTH_HEADER_PATTERN.sub(rf"\1{MASK}", masked)
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
