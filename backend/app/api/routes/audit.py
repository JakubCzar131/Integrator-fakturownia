from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.audit import AuditLog
from app.models.user import User
from app.repositories.pagination import PageParams, apply_sort, paginate
from app.schemas.common import Page
from app.schemas.domain import AuditLogOut
from app.security.auth import require_any_role

router = APIRouter(prefix="/audit-log", tags=["audit"])


@router.get("", response_model=Page[AuditLogOut])
def list_audit_log(
    params: PageParams = Depends(),
    action: str | None = None,
    object_type: str | None = None,
    user_email: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action == action)
    if object_type:
        query = query.where(AuditLog.object_type == object_type)
    if user_email:
        query = query.where(AuditLog.user_email.ilike(f"%{user_email}%"))
    if date_from:
        query = query.where(AuditLog.created_at >= date_from)
    if date_to:
        query = query.where(AuditLog.created_at <= date_to)
    sortable = {
        "id": AuditLog.id, "created_at": AuditLog.created_at,
        "action": AuditLog.action, "object_type": AuditLog.object_type,
        "user_email": AuditLog.user_email,
    }
    if not params.sort_by:
        query = query.order_by(AuditLog.id.desc())
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)
    return {
        **{k: result[k] for k in ("total", "page", "per_page", "pages")},
        "items": [AuditLogOut.model_validate(row[0]) for row in result["rows"]],
    }
