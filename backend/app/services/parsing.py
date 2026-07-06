"""Tolerant parsers for raw Fakturownia payload values."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


def to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def to_bool(value: Any) -> bool:
    return value in (True, "true", "True", 1, "1", "yes")


def to_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def to_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def to_str(value: Any, max_length: int | None = None) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)
    return text[:max_length] if max_length else text


def payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_text(value: str | None) -> str:
    """Normalization used for alias / mapping signature matching."""
    if not value:
        return ""
    return " ".join(value.strip().lower().split())


def mapping_signature(
    name: str | None, code: str | None = None, ean: str | None = None, unit: str | None = None
) -> str:
    canonical = "|".join(
        normalize_text(part) for part in (name, code, ean, unit)
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
