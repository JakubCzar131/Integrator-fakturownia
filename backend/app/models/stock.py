"""Local warehouse: opening balances, adjustments, ledger, balances.

Design principles:

* ``opening_balances`` and ``local_stock_adjustments`` are *source* records
  entered by operators.  They are append-only; a mistake is corrected with a
  reversal adjustment, never by deleting history.
* ``local_stock_ledger`` is a *derived* projection built deterministically
  from all sources (opening balances, sales invoices, corrections, imported
  warehouse actions, manual adjustments).  It can be rebuilt from scratch at
  any time (``POST /stock/recalculate``).
* ``local_stock_balances`` caches the current balance per product+warehouse.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

Qty = sa.Numeric(18, 4)


class OpeningBalance(Base):
    __tablename__ = "opening_balances"
    __table_args__ = (
        sa.UniqueConstraint("product_id", "warehouse_id", name="uq_opening_balance_product_wh"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        sa.ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    warehouse_id: Mapped[int] = mapped_column(
        sa.ForeignKey("warehouses.id", ondelete="CASCADE"), index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Qty)
    as_of_date: Mapped[date] = mapped_column(sa.Date, index=True)
    note: Mapped[str | None] = mapped_column(sa.Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )


class LocalStockAdjustment(Base):
    __tablename__ = "local_stock_adjustments"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        sa.ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    warehouse_id: Mapped[int] = mapped_column(
        sa.ForeignKey("warehouses.id", ondelete="CASCADE"), index=True
    )
    quantity_change: Mapped[Decimal] = mapped_column(Qty)
    description: Mapped[str] = mapped_column(sa.Text)  # required business reason
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), index=True)
    is_reversal: Mapped[bool] = mapped_column(default=False)
    reverses_adjustment_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("local_stock_adjustments.id", ondelete="SET NULL")
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class LocalStockLedgerEntry(Base):
    __tablename__ = "local_stock_ledger"
    __table_args__ = (
        sa.Index("ix_ledger_product_wh_seq", "product_id", "warehouse_id", "sequence"),
    )

    id: Mapped[int] = mapped_column(
        sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True
    )
    product_id: Mapped[int] = mapped_column(
        sa.ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    warehouse_id: Mapped[int] = mapped_column(
        sa.ForeignKey("warehouses.id", ondelete="CASCADE"), index=True
    )
    movement_type: Mapped[str] = mapped_column(sa.String(40), index=True)
    quantity_change: Mapped[Decimal] = mapped_column(Qty)
    balance_before: Mapped[Decimal] = mapped_column(Qty)
    balance_after: Mapped[Decimal] = mapped_column(Qty)
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), index=True)
    sequence: Mapped[int] = mapped_column(sa.BigInteger().with_variant(sa.Integer, "sqlite"))

    source_invoice_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("fakturownia_invoices.id", ondelete="SET NULL"), index=True
    )
    source_invoice_position_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("fakturownia_invoice_positions.id", ondelete="SET NULL"), index=True
    )
    source_adjustment_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("local_stock_adjustments.id", ondelete="SET NULL")
    )
    source_opening_balance_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("opening_balances.id", ondelete="SET NULL")
    )
    source_warehouse_action_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("warehouse_actions.id", ondelete="SET NULL")
    )
    description: Mapped[str | None] = mapped_column(sa.Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class LocalStockBalance(Base):
    __tablename__ = "local_stock_balances"
    __table_args__ = (
        sa.UniqueConstraint("product_id", "warehouse_id", name="uq_stock_balance_product_wh"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        sa.ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    warehouse_id: Mapped[int] = mapped_column(
        sa.ForeignKey("warehouses.id", ondelete="CASCADE"), index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    last_movement_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_sale_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    recalculated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
