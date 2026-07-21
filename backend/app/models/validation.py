from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, JSONVariant

Qty = sa.Numeric(18, 4)


class ValidationRun(Base):
    __tablename__ = "validation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(sa.String(20), default="RUNNING", index=True)
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(sa.Float)
    triggered_by_user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    invoices_checked: Mapped[int] = mapped_column(default=0)
    positions_checked: Mapped[int] = mapped_column(default=0)
    issues_created: Mapped[int] = mapped_column(default=0)
    issues_auto_resolved: Mapped[int] = mapped_column(default=0)
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())
    message: Mapped[str | None] = mapped_column(sa.Text)


class ValidationIssue(Base):
    __tablename__ = "validation_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    validation_run_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("validation_runs.id", ondelete="SET NULL"), index=True
    )
    issue_type: Mapped[str] = mapped_column(sa.String(50), index=True)
    status: Mapped[str] = mapped_column(sa.String(30), index=True)
    severity: Mapped[str] = mapped_column(sa.String(20), index=True)

    invoice_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("fakturownia_invoices.id", ondelete="CASCADE"), index=True
    )
    invoice_position_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("fakturownia_invoice_positions.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    warehouse_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("warehouses.id", ondelete="SET NULL"), index=True
    )

    quantity: Mapped[Decimal | None] = mapped_column(Qty)
    stock_before: Mapped[Decimal | None] = mapped_column(Qty)
    stock_after: Mapped[Decimal | None] = mapped_column(Qty)

    technical_description: Mapped[str | None] = mapped_column(sa.Text)
    business_description: Mapped[str | None] = mapped_column(sa.Text)
    recommended_action: Mapped[str | None] = mapped_column(sa.Text)

    # Stable key so re-running validation updates existing open issues instead
    # of duplicating them: sha256(issue_type + invoice/position/product refs).
    dedupe_key: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    resolved_by_user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )

    comments: Mapped[list["ValidationIssueComment"]] = relationship(
        back_populates="issue", cascade="all, delete-orphan", lazy="selectin",
        order_by="ValidationIssueComment.created_at",
    )


class ValidationIssueComment(Base):
    __tablename__ = "validation_issue_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        sa.ForeignKey("validation_issues.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    user_email: Mapped[str | None] = mapped_column(sa.String(255))
    body: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    issue: Mapped[ValidationIssue] = relationship(back_populates="comments")
