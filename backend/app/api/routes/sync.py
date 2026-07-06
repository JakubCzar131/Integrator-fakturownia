from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.database.session import SessionLocal, get_db
from app.api.deps import build_fakturownia_client
from app.models.enums import AuditAction, SyncRunStatus, SyncRunType
from app.models.sync import SyncRun
from app.models.user import User
from app.repositories.pagination import PageParams, apply_sort, paginate
from app.schemas.common import MessageResponse, Page
from app.schemas.domain import SyncRunOut
from app.security.auth import client_ip, require_any_role, require_operator

router = APIRouter(prefix="/sync", tags=["sync"])
logger = logging.getLogger(__name__)

_sync_lock = threading.Lock()


def _run_sync_in_background(run_type: SyncRunType, user_id: int | None) -> None:
    from app.services.sync_service import SyncService

    db = SessionLocal()
    try:
        user = db.get(User, user_id) if user_id else None
        client = build_fakturownia_client()
        try:
            service = SyncService(db, client)
            if run_type == SyncRunType.FULL:
                service.run_full_sync(user)
            else:
                service.run_incremental_sync(user)
        finally:
            client.close()
    except Exception:
        logger.exception("Background sync failed")
    finally:
        _sync_lock.release()
        db.close()


def _start_sync(run_type: SyncRunType, user: User, db: Session, request: Request) -> MessageResponse:
    if not _sync_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Synchronizacja jest już w toku")
    record_audit(
        db, AuditAction.SYNC_STARTED, user=user, object_type="sync",
        description=f"Uruchomiono synchronizację {run_type}",
        ip_address=client_ip(request),
    )
    db.commit()
    thread = threading.Thread(
        target=_run_sync_in_background, args=(run_type, user.id), daemon=True
    )
    thread.start()
    return MessageResponse(
        message=f"Synchronizacja {run_type} została uruchomiona w tle",
        detail={"run_type": str(run_type)},
    )


@router.post("/full", response_model=MessageResponse)
def run_full_sync(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> MessageResponse:
    """Full sync. Performs exclusively GET requests towards Fakturownia."""
    return _start_sync(SyncRunType.FULL, user, db, request)


@router.post("/incremental", response_model=MessageResponse)
def run_incremental_sync(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> MessageResponse:
    return _start_sync(SyncRunType.INCREMENTAL, user, db, request)


@router.get("/runs", response_model=Page[SyncRunOut])
def list_sync_runs(
    params: PageParams = Depends(),
    status: str | None = None,
    run_type: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    query = select(SyncRun)
    if status:
        query = query.where(SyncRun.status == status)
    if run_type:
        query = query.where(SyncRun.run_type == run_type)
    sortable = {
        "id": SyncRun.id, "started_at": SyncRun.started_at, "status": SyncRun.status,
        "run_type": SyncRun.run_type, "duration_seconds": SyncRun.duration_seconds,
        "records_fetched": SyncRun.records_fetched, "error_count": SyncRun.error_count,
    }
    if not params.sort_by:
        query = query.order_by(SyncRun.id.desc())
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)
    return {
        **{k: result[k] for k in ("total", "page", "per_page", "pages")},
        "items": [SyncRunOut.model_validate(row[0]) for row in result["rows"]],
    }


@router.get("/status")
def sync_status(db: Session = Depends(get_db), _: User = Depends(require_any_role)) -> dict:
    last = db.execute(
        select(SyncRun).order_by(SyncRun.id.desc()).limit(1)
    ).scalars().first()
    last_success = db.execute(
        select(SyncRun)
        .where(SyncRun.status == str(SyncRunStatus.SUCCESS))
        .order_by(SyncRun.id.desc()).limit(1)
    ).scalars().first()
    return {
        "in_progress": _sync_lock.locked(),
        "last_run": SyncRunOut.model_validate(last).model_dump() if last else None,
        "last_success": SyncRunOut.model_validate(last_success).model_dump()
        if last_success else None,
    }
