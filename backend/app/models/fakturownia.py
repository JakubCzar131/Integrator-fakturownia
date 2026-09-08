"""Mirror tables for data fetched (GET-only) from Fakturownia.

These tables are a local, read-only copy of the source system.  They are only
ever written by the sync service; the application never pushes anything back.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, JSONVariant

Qty = sa.Numeric(18, 4)
Money = sa.Numeric(18, 2)


class SyncedMixin:
    """Common bookkeeping columns for mirrored resources."""

    payload_hash: Mapped[str | None] = mapped_column(sa.String(64))
    is_deleted_upstream: Mapped[bool] = mapped_column(default=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    last_synced_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class FakturowniaClient(Base, SyncedMixin):
    __tablename__ = "fakturownia_clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    fakturownia_id: Mapped[int] = mapped_column(sa.BigInteger, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(sa.String(500), index=True)
    tax_no: Mapped[str | None] = mapped_column(sa.String(50), index=True)
    email: Mapped[str | None] = mapped_column(sa.String(255))
    phone: Mapped[str | None] = mapped_column(sa.String(100))
    street: Mapped[str | None] = mapped_column(sa.String(255))
    city: Mapped[str | None] = mapped_column(sa.String(255))
    post_code: Mapped[str | None] = mapped_column(sa.String(20))
    country: Mapped[str | None] = mapped_column(sa.String(100))
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())


class FakturowniaProduct(Base, SyncedMixin):
    __tablename__ = "fakturownia_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    fakturownia_id: Mapped[int] = mapped_column(sa.BigInteger, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(sa.String(500), index=True)
    code: Mapped[str | None] = mapped_column(sa.String(255), index=True)
    ean: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    sku: Mapped[str | None] = mapped_column(sa.String(255))
    unit: Mapped[str | None] = mapped_column(sa.String(50))
    tax: Mapped[str | None] = mapped_column(sa.String(20))
    price_net: Mapped[Decimal | None] = mapped_column(Money)
    price_gross: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str | None] = mapped_column(sa.String(10))
    category_fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger)
    quantity: Mapped[Decimal | None] = mapped_column(Qty)  # global stock reported by Fakturownia
    is_service_upstream: Mapped[bool | None] = mapped_column()  # from payload if present
    disabled: Mapped[bool] = mapped_column(default=False)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())


class FakturowniaProductStock(Base):
    """Per-warehouse stock level reported by Fakturownia (GET products.json?warehouse_id=...)."""

    __tablename__ = "fakturownia_product_stocks"
    __table_args__ = (
        sa.UniqueConstraint("product_fakturownia_id", "warehouse_fakturownia_id",
                            name="uq_fprod_stock_product_warehouse"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_fakturownia_id: Mapped[int] = mapped_column(sa.BigInteger, index=True)
    warehouse_fakturownia_id: Mapped[int] = mapped_column(sa.BigInteger, index=True)
    quantity: Mapped[Decimal | None] = mapped_column(Qty)
    fetched_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class Warehouse(Base, SyncedMixin):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(primary_key=True)
    fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger, unique=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(255), index=True)
    kind: Mapped[str | None] = mapped_column(sa.String(50))
    description: Mapped[str | None] = mapped_column(sa.Text)
    is_default: Mapped[bool] = mapped_column(default=False)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())


class FakturowniaInvoice(Base, SyncedMixin):
    __tablename__ = "fakturownia_invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    fakturownia_id: Mapped[int] = mapped_column(sa.BigInteger, unique=True, index=True)
    number: Mapped[str | None] = mapped_column(sa.String(100), index=True)
    kind: Mapped[str | None] = mapped_column(sa.String(50), index=True)  # vat / correction / proforma / receipt ...
    invoice_status: Mapped[str | None] = mapped_column(sa.String(50), index=True)
    income: Mapped[bool | None] = mapped_column()  # True = sales document
    issue_date: Mapped[date | None] = mapped_column(sa.Date, index=True)
    sell_date: Mapped[date | None] = mapped_column(sa.Date, index=True)
    client_fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger, index=True)
    buyer_name: Mapped[str | None] = mapped_column(sa.String(500), index=True)
    buyer_tax_no: Mapped[str | None] = mapped_column(sa.String(50))
    seller_name: Mapped[str | None] = mapped_column(sa.String(500))
    department_fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger)
    warehouse_fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger, index=True)
    currency: Mapped[str | None] = mapped_column(sa.String(10))
    total_net: Mapped[Decimal | None] = mapped_column(Money)
    total_gross: Mapped[Decimal | None] = mapped_column(Money)
    paid_amount: Mapped[Decimal | None] = mapped_column(Money)
    is_correction: Mapped[bool] = mapped_column(default=False)
    corrected_invoice_fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger, index=True)
    is_cancelled: Mapped[bool] = mapped_column(default=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())

    positions: Mapped[list["FakturowniaInvoicePosition"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", lazy="selectin"
    )


class FakturowniaInvoicePosition(Base):
    __tablename__ = "fakturownia_invoice_positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger, unique=True, index=True)
    invoice_id: Mapped[int] = mapped_column(
        sa.ForeignKey("fakturownia_invoices.id", ondelete="CASCADE"), index=True
    )
    invoice_fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger, index=True)
    product_fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger, index=True)
    name: Mapped[str | None] = mapped_column(sa.String(1000), index=True)
    description: Mapped[str | None] = mapped_column(sa.Text)
    code: Mapped[str | None] = mapped_column(sa.String(255))
    quantity: Mapped[Decimal | None] = mapped_column(Qty)
    quantity_unit: Mapped[str | None] = mapped_column(sa.String(50))
    price_net: Mapped[Decimal | None] = mapped_column(Money)
    price_gross: Mapped[Decimal | None] = mapped_column(Money)
    total_price_net: Mapped[Decimal | None] = mapped_column(Money)
    total_price_gross: Mapped[Decimal | None] = mapped_column(Money)
    tax: Mapped[str | None] = mapped_column(sa.String(20))
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())

    # Local mapping result (written only locally, never pushed upstream).
    mapped_product_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    mapping_status: Mapped[str | None] = mapped_column(sa.String(20), index=True)
    mapping_match_type: Mapped[str | None] = mapped_column(sa.String(20))

    invoice: Mapped[FakturowniaInvoice] = relationship(back_populates="positions")


class WarehouseDocument(Base, SyncedMixin):
    __tablename__ = "warehouse_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    fakturownia_id: Mapped[int] = mapped_column(sa.BigInteger, unique=True, index=True)
    kind: Mapped[str | None] = mapped_column(sa.String(20), index=True)  # PZ / WZ / MM / RW / PW ...
    number: Mapped[str | None] = mapped_column(sa.String(100), index=True)
    warehouse_fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger, index=True)
    issue_date: Mapped[date | None] = mapped_column(sa.Date, index=True)
    client_fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger)
    invoice_fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger, index=True)
    description: Mapped[str | None] = mapped_column(sa.Text)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())
    # Hash of the extracted position list; positions are rebuilt only when it
    # changes, so re-running a sync does not churn through every document.
    positions_built_hash: Mapped[str | None] = mapped_column(sa.String(64))

    positions: Mapped[list["WarehouseDocumentPosition"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", lazy="selectin"
    )


class WarehouseDocumentPosition(Base):
    """Normalized position of a warehouse document (PZ / PW / WZ / RW / MM).

    Fakturownia returns positions inside the document payload (and, for some
    accounts, only as ``warehouse_actions``); both sources are folded into this
    table so goods receipts can be aggregated with plain SQL.  ``document_kind``
    and ``issue_date`` are denormalized from the header for that reason.
    """

    __tablename__ = "warehouse_document_positions"
    __table_args__ = (
        sa.Index("ix_wdp_product_kind", "mapped_product_id", "document_kind"),
        sa.Index("ix_wdp_issue_date", "issue_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        sa.ForeignKey("warehouse_documents.id", ondelete="CASCADE"), index=True
    )
    document_kind: Mapped[str | None] = mapped_column(sa.String(20), index=True)
    fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger, unique=True, index=True)
    source_action_fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger, index=True)
    product_fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger, index=True)
    mapped_product_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    mapping_status: Mapped[str | None] = mapped_column(sa.String(20), index=True)
    mapping_match_type: Mapped[str | None] = mapped_column(sa.String(20))
    name: Mapped[str | None] = mapped_column(sa.String(1000))
    code: Mapped[str | None] = mapped_column(sa.String(255))
    quantity: Mapped[Decimal | None] = mapped_column(Qty)
    quantity_unit: Mapped[str | None] = mapped_column(sa.String(50))
    purchase_price_net: Mapped[Decimal | None] = mapped_column(Money)
    issue_date: Mapped[date | None] = mapped_column(sa.Date)
    warehouse_fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger, index=True)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())

    document: Mapped["WarehouseDocument"] = relationship(back_populates="positions")


class WarehouseAction(Base, SyncedMixin):
    __tablename__ = "warehouse_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    fakturownia_id: Mapped[int] = mapped_column(sa.BigInteger, unique=True, index=True)
    warehouse_document_fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger, index=True)
    warehouse_fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger, index=True)
    product_fakturownia_id: Mapped[int | None] = mapped_column(sa.BigInteger, index=True)
    kind: Mapped[str | None] = mapped_column(sa.String(20))
    quantity: Mapped[Decimal | None] = mapped_column(Qty)
    price_net: Mapped[Decimal | None] = mapped_column(Money)
    occurred_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())


class FakturowniaCategory(Base, SyncedMixin):
    __tablename__ = "fakturownia_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    fakturownia_id: Mapped[int] = mapped_column(sa.BigInteger, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(sa.String(255))
    description: Mapped[str | None] = mapped_column(sa.Text)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())


class FakturowniaDepartment(Base, SyncedMixin):
    __tablename__ = "fakturownia_departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    fakturownia_id: Mapped[int] = mapped_column(sa.BigInteger, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(sa.String(500))
    shortcut: Mapped[str | None] = mapped_column(sa.String(100))
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())


class FakturowniaPayment(Base, SyncedMixin):
    __tablename__ = "fakturownia_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    fakturownia_id: Mapped[int] = mapped_column(sa.BigInteger, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(sa.String(500))
    price: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str | None] = mapped_column(sa.String(10))
    paid_date: Mapped[date | None] = mapped_column(sa.Date)
    invoice_fakturownia_ids: Mapped[list[Any] | None] = mapped_column(JSONVariant())
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())


class FakturowniaPriceList(Base, SyncedMixin):
    __tablename__ = "fakturownia_price_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    fakturownia_id: Mapped[int] = mapped_column(sa.BigInteger, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(sa.String(255))
    currency: Mapped[str | None] = mapped_column(sa.String(10))
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())
