"""Worker draining the ``sync_jobs`` outbox (currently: SkyShop writes).

Why a PostgreSQL outbox instead of Celery/Redis: the bottleneck is the
receiving API (one request per second), not worker throughput.  A table gives
durability, transactional coupling with the data change that requested the push
and zero extra infrastructure.  Job selection uses ``FOR UPDATE SKIP LOCKED``
so several application instances can share the queue safely; the SQLite test
database simply ignores the locking clause.

Failure handling: exponential backoff per attempt, and after ``max_attempts``
the job lands in ``FAILED`` (a dead-letter row visible in the UI with a
"Ponów" button).  Configuration problems (integration not configured, kill
switch off) are not retried — they end as ``SKIPPED``, because retrying cannot
help until a human changes something.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import SyncJobStatus
from app.models.sync import SyncJob
from app.services.skyshop_client import (
    SkyShopNotConfigured,
    SkyShopWriteBlocked,
)
from app.services.skyshop_service import SkyShopService, SkyShopValidationError, backoff_delay

logger = logging.getLogger(__name__)

# Errors that a retry cannot fix — a person has to intervene first.
NON_RETRYABLE = (SkyShopNotConfigured, SkyShopWriteBlocked, SkyShopValidationError)


def claim_jobs(db: Session, limit: int) -> list[SyncJob]:
    """Atomically claim up to ``limit`` due jobs."""
    now = datetime.now(timezone.utc)
    query = (
        select(SyncJob)
        .where(
            SyncJob.status == str(SyncJobStatus.PENDING),
            SyncJob.next_attempt_at <= now,
        )
        .order_by(SyncJob.priority, SyncJob.next_attempt_at, SyncJob.id)
        .limit(limit)
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    jobs = list(db.execute(query).scalars())
    for job in jobs:
        job.status = str(SyncJobStatus.RUNNING)
        job.started_at = now
        job.attempts += 1
    db.commit()
    return jobs


def run_job(db: Session, job: SyncJob, service: SkyShopService) -> None:
    """Execute one claimed job and persist its outcome."""
    try:
        result = service.execute_job(job)
        job.status = str(SyncJobStatus.SUCCESS)
        job.result = _jsonable(result)
        job.last_error = None
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    except NON_RETRYABLE as exc:
        db.rollback()
        job = db.merge(job)
        job.status = str(SyncJobStatus.SKIPPED)
        job.last_error = str(exc)
        job.finished_at = datetime.now(timezone.utc)
        logger.info("Zadanie #%s pominięte: %s", job.id, exc)
        db.commit()
    except Exception as exc:
        db.rollback()
        job = db.merge(job)
        job.last_error = str(exc)[:4000]
        if job.attempts >= job.max_attempts:
            job.status = str(SyncJobStatus.FAILED)
            job.finished_at = datetime.now(timezone.utc)
            logger.error(
                "Zadanie #%s trwale nieudane po %d próbach: %s", job.id, job.attempts, exc
            )
        else:
            job.status = str(SyncJobStatus.PENDING)
            job.next_attempt_at = datetime.now(timezone.utc) + backoff_delay(job.attempts)
            logger.warning(
                "Zadanie #%s nieudane (próba %d/%d), ponowienie o %s: %s",
                job.id, job.attempts, job.max_attempts, job.next_attempt_at, exc,
            )
        db.commit()


def process_pending_jobs(
    db: Session, limit: int | None = None, service: SkyShopService | None = None
) -> dict[str, int]:
    """Claim and execute a batch of jobs. Returns per-status counters."""
    limit = limit or get_settings().job_worker_batch_size
    jobs = claim_jobs(db, limit)
    stats = {"claimed": len(jobs), "success": 0, "failed": 0, "skipped": 0, "retry": 0}
    if not jobs:
        return stats

    owns_service = service is None
    service = service or SkyShopService(db)
    try:
        for job in jobs:
            run_job(db, job, service)
            status = job.status
            if status == str(SyncJobStatus.SUCCESS):
                stats["success"] += 1
            elif status == str(SyncJobStatus.FAILED):
                stats["failed"] += 1
            elif status == str(SyncJobStatus.SKIPPED):
                stats["skipped"] += 1
            else:
                stats["retry"] += 1
    finally:
        if owns_service:
            service.close()
    return stats


def worker_tick() -> None:
    """Scheduler entry point: one pass over the queue."""
    from app.database.session import SessionLocal

    db = SessionLocal()
    try:
        stats = process_pending_jobs(db)
        if stats["claimed"]:
            logger.info("Kolejka SkyShop: %s", stats)
    except Exception:
        logger.exception("Przebieg workera kolejki nie powiódł się")
    finally:
        db.close()


def _jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)
