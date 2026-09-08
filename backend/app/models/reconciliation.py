"""Snapshot tables for the document reconciliation table ("Tabela Rozliczeniowa").

Reconciliation compares three independent sources for every product/warehouse:

* stock reported by Fakturownia,
* goods receipts documented as PZ/PW,
* outbound movements documented on sales invoices and corrections.

The result is materialized per run, so the UI paginates/sorts an indexed table
instead of recomputing heavy aggregates on every request, and the run history
shows *when* a discrepancy appeared.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, JSONVariant

Qty = sa.Numeric(18, 4)


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(sa.Float)
    triggered_by_user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    trigger: Mapped[str] = mapped_column(sa.String(20), default="MANUAL")  # MANUAL | SYNC
    sync_run_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("sync_runs.id", ondelete="SET NULL")
    )
    line_count: Mapped[int] = mapped_column(default=0)
    discrepancy_count: Mapped[int] = mapped_column(default=0)
    tolerance: Mapped[Decimal | None] = mapped_column(Qty)
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())


class StockReconciliationLine(Base):
    __tablename__ = "stock_reconciliation_lines"
    __table_args__ = (
        sa.UniqueConstraint(
            "run_id", "product_id", "warehouse_id", name="uq_reconciliation_line"
        ),
        sa.Index("ix_reconciliation_run_status", "run_id", "status"),
    )

    id: Mapped[int] = mapped_column(
        sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True
    )
    run_id: Mapped[int] = mapped_column(
        sa.ForeignKey("reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(
        sa.ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    warehouse_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("warehouses.id", ondelete="CASCADE"), index=True
    )
    fakturownia_stock: Mapped[Decimal | None] = mapped_column(Qty)
    inbound_pz: Mapped[Decimal] = mapped_column(Qty, default=0)
    inbound_pw: Mapped[Decimal] = mapped_column(Qty, default=0)
    outbound_documents: Mapped[Decimal] = mapped_column(Qty, default=0)
    sold_invoices: Mapped[Decimal] = mapped_column(Qty, default=0)
    corrections: Mapped[Decimal] = mapped_column(Qty, default=0)
    opening_balance: Mapped[Decimal | None] = mapped_column(Qty)
    local_ledger_stock: Mapped[Decimal | None] = mapped_column(Qty)
    computed_stock: Mapped[Decimal] = mapped_column(Qty, default=0)
    difference: Mapped[Decimal | None] = mapped_column(Qty)
    status: Mapped[str] = mapped_column(sa.String(20), index=True)
    computed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
