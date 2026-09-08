"""In-process background jobs (APScheduler).

Two independent schedules:

* optional periodic incremental sync from Fakturownia,
* the outbox worker draining ``sync_jobs`` (SkyShop writes) at a steady pace.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import get_settings

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _scheduled_incremental_sync() -> None:
    # Reuse the same locking path as the API so manual and scheduled syncs
    # never run concurrently.
    from app.api.routes.sync import _run_sync_in_background, _sync_lock
    from app.models.enums import SyncRunType

    if not _sync_lock.acquire(blocking=False):
        logger.info("Scheduled sync skipped — another sync is already running")
        return
    _run_sync_in_background(SyncRunType.INCREMENTAL, user_id=None)


def start_scheduler() -> None:
    global _scheduler
    settings = get_settings()
    if not (settings.sync_schedule_enabled or settings.job_worker_enabled):
        logger.info("Scheduler disabled (SYNC_SCHEDULE_ENABLED / JOB_WORKER_ENABLED = false)")
        return

    _scheduler = BackgroundScheduler(timezone="UTC")
    if settings.sync_schedule_enabled:
        _scheduler.add_job(
            _scheduled_incremental_sync,
            "interval",
            minutes=settings.sync_interval_minutes,
            id="incremental_sync",
            max_instances=1,
            coalesce=True,
        )
        logger.info(
            "Sync scheduler started: incremental sync every %d minutes",
            settings.sync_interval_minutes,
        )
    if settings.job_worker_enabled:
        from app.services.sync_worker import worker_tick

        _scheduler.add_job(
            worker_tick,
            "interval",
            seconds=settings.job_worker_interval_seconds,
            id="sync_job_worker",
            max_instances=1,
            coalesce=True,
        )
        logger.info(
            "Outbox worker started: every %d s, batch %d",
            settings.job_worker_interval_seconds,
            settings.job_worker_batch_size,
        )
    _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
