"""Local audit trail. Every local mutation is recorded here (append-only)."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.logging_config import mask_secrets
from app.models.audit import AuditLog
from app.models.enums import AuditAction
from app.models.user import User

logger = logging.getLogger(__name__)


def record_audit(
    db: Session,
    action: AuditAction | str,
    *,
    user: User | None = None,
    object_type: str | None = None,
    object_id: Any | None = None,
    description: str | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user.id if user else None,
        user_email=user.email if user else None,
        action=str(action),
        object_type=object_type,
        object_id=str(object_id) if object_id is not None else None,
        description=mask_secrets(description) if description else None,
        old_value=old_value,
        new_value=new_value,
        ip_address=ip_address,
    )
    db.add(entry)
    return entry


def skyshop_write_audit_callback(session_factory, user_id: int | None = None) -> Any:
    """Build the audit callback wired into the SkyShop client.

    Every attempted mutation (executed, dry-run or blocked by the kill switch)
    is persisted in its own short-lived session, so the trail survives even if
    the surrounding job transaction is rolled back.
    """

    def _callback(
        action: str,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        response: Any,
        blocked_reason: str | None = None,
    ) -> None:
        session: Session = session_factory()
        try:
            user = session.get(User, user_id) if user_id else None
            description = (
                f"SkyShop {method} {path}"
                if not blocked_reason
                else f"SkyShop {method} {path} — zablokowano ({blocked_reason})"
            )
            record_audit(
                session,
                AuditAction.SKYSHOP_WRITE_BLOCKED if blocked_reason else AuditAction.SKYSHOP_WRITE,
                user=user,
                object_type="skyshop_api",
                object_id=path,
                description=description,
                new_value={
                    "method": method,
                    "payload": _jsonable(payload),
                    "response": _jsonable(response),
                    "blocked_reason": blocked_reason,
                },
            )
            session.commit()
        except Exception:  # pragma: no cover - auditing must not break the write
            session.rollback()
            logger.exception("Could not persist SkyShop write audit entry")
        finally:
            session.close()

    return _callback


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def readonly_violation_audit_callback(session_factory) -> Any:
    """Build the audit callback wired into the Fakturownia read-only client.

    Uses a dedicated short-lived session so the violation is persisted even if
    the caller's transaction rolls back afterwards.
    """

    def _callback(method: str, url: str, description: str) -> None:
        session: Session = session_factory()
        try:
            record_audit(
                session,
                AuditAction.READONLY_VIOLATION_BLOCKED,
                object_type="fakturownia_api",
                object_id=method,
                description=f"{description}: {mask_secrets(url)}",
            )
            session.commit()
        except Exception:  # pragma: no cover
            session.rollback()
            logger.exception("Could not persist read-only violation audit entry")
        finally:
            session.close()

    return _callback
