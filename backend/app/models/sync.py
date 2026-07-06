from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, JSONVariant


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_type: Mapped[str] = mapped_column(sa.String(20), index=True)  # FULL | INCREMENTAL
    status: Mapped[str] = mapped_column(sa.String(20), index=True, default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(sa.Float)
    triggered_by_user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    records_fetched: Mapped[int] = mapped_column(default=0)
    records_created: Mapped[int] = mapped_column(default=0)
    records_updated: Mapped[int] = mapped_column(default=0)
    records_unchanged: Mapped[int] = mapped_column(default=0)
    error_count: Mapped[int] = mapped_column(default=0)
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())
    errors: Mapped[list[Any] | None] = mapped_column(JSONVariant())
    message: Mapped[str | None] = mapped_column(sa.Text)


class SourceSnapshot(Base):
    """Raw JSON payload of every record fetched from Fakturownia (append-only)."""

    __tablename__ = "source_snapshots"
    __table_args__ = (
        sa.Index("ix_source_snapshots_resource_external", "resource_type", "external_id"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True)
    sync_run_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("sync_runs.id", ondelete="SET NULL")
    )
    resource_type: Mapped[str] = mapped_column(sa.String(50))
    external_id: Mapped[int | None] = mapped_column(sa.BigInteger)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONVariant())
    payload_hash: Mapped[str] = mapped_column(sa.String(64), index=True)
    fetched_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
