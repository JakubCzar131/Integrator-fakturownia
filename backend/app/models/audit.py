from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, JSONVariant


class AuditLog(Base):
    """Append-only log of every local operation (never modified, never deleted)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    user_email: Mapped[str | None] = mapped_column(sa.String(255))
    action: Mapped[str] = mapped_column(sa.String(50), index=True)
    object_type: Mapped[str | None] = mapped_column(sa.String(100), index=True)
    object_id: Mapped[str | None] = mapped_column(sa.String(100))
    description: Mapped[str | None] = mapped_column(sa.Text)
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())
    ip_address: Mapped[str | None] = mapped_column(sa.String(64))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), index=True
    )
