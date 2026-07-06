from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, JSONVariant


class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(sa.String(100), unique=True, index=True)
    value: Mapped[Any | None] = mapped_column(JSONVariant())
    description: Mapped[str | None] = mapped_column(sa.Text)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )


class SavedFilter(Base):
    __tablename__ = "saved_filters"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    table_key: Mapped[str] = mapped_column(sa.String(100), index=True)
    name: Mapped[str] = mapped_column(sa.String(255))
    filters: Mapped[dict[str, Any]] = mapped_column(JSONVariant())
    is_default: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class TableColumnPreference(Base):
    __tablename__ = "table_column_preferences"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "table_key", name="uq_column_pref_user_table"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    table_key: Mapped[str] = mapped_column(sa.String(100))
    columns: Mapped[dict[str, Any]] = mapped_column(JSONVariant())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )


class ReportExport(Base):
    __tablename__ = "report_exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    report_key: Mapped[str] = mapped_column(sa.String(100), index=True)
    format: Mapped[str] = mapped_column(sa.String(10))
    row_count: Mapped[int] = mapped_column(default=0)
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())
    file_name: Mapped[str | None] = mapped_column(sa.String(255))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
