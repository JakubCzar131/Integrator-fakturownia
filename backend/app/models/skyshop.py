"""SkyShop mirror, product links and locally curated PIM content.

Everything the integrator knows about the webshop is kept in a local mirror
(``skyshop_products`` / ``skyshop_categories``).  Matching, verification and
delta detection run against that mirror, so a "is this product in the shop?"
question costs zero API calls — which matters a lot given the platform limit
of one request per second.

``skyshop_product_links`` is the heart of the integration: one row per local
product, holding the shop identifier, the match status and the fingerprints of
what was last pushed (stock quantity and PIM content hash).  Those fingerprints
turn every synchronization into a delta operation.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, JSONVariant

Qty = sa.Numeric(18, 4)
Money = sa.Numeric(18, 2)


class SkyShopProduct(Base):
    """Read-only mirror of a product that exists in the webshop."""

    __tablename__ = "skyshop_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    skyshop_id: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    sku: Mapped[str | None] = mapped_column(sa.String(255), index=True)
    ean: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    name: Mapped[str | None] = mapped_column(sa.String(1000), index=True)
    price_gross: Mapped[Decimal | None] = mapped_column(Money)
    quantity: Mapped[Decimal | None] = mapped_column(Qty)
    category_skyshop_id: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    is_active: Mapped[bool | None] = mapped_column()
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())
    payload_hash: Mapped[str | None] = mapped_column(sa.String(64))
    first_seen_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    last_synced_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    is_deleted_upstream: Mapped[bool] = mapped_column(default=False)


class SkyShopCategory(Base):
    __tablename__ = "skyshop_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    skyshop_id: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(sa.String(500))
    parent_skyshop_id: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    path: Mapped[str | None] = mapped_column(sa.Text)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant())
    last_synced_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class SkyShopProductLink(Base):
    """Local product ↔ shop product relation plus delta-push fingerprints."""

    __tablename__ = "skyshop_product_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        sa.ForeignKey("products.id", ondelete="CASCADE"), unique=True, index=True
    )
    skyshop_id: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    status: Mapped[str] = mapped_column(sa.String(20), default="MISSING", index=True)
    match_type: Mapped[str | None] = mapped_column(sa.String(20))  # SKU | EAN | NAME | MANUAL
    candidate_skyshop_ids: Mapped[list[Any] | None] = mapped_column(JSONVariant())
    last_pushed_stock: Mapped[Decimal | None] = mapped_column(Qty)
    last_pushed_content_hash: Mapped[str | None] = mapped_column(sa.String(64))
    last_pushed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(sa.Text)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )


class SkyShopCategoryMapping(Base):
    """Local category (free-text) → shop category identifier."""

    __tablename__ = "skyshop_category_mappings"
    __table_args__ = (
        sa.UniqueConstraint("local_category", name="uq_skyshop_category_mappings_local"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    local_category: Mapped[str] = mapped_column(sa.String(255), index=True)
    skyshop_category_id: Mapped[str] = mapped_column(sa.String(64))
    created_by_user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )


class ProductContent(Base):
    """Locally maintained PIM data — the source of truth for the webshop."""

    __tablename__ = "product_contents"

    product_id: Mapped[int] = mapped_column(
        sa.ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    description_html: Mapped[str | None] = mapped_column(sa.Text)
    short_description: Mapped[str | None] = mapped_column(sa.Text)
    images: Mapped[list[Any]] = mapped_column(JSONVariant(), default=list)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONVariant(), default=dict)
    price_gross: Mapped[Decimal | None] = mapped_column(Money)
    vat_rate: Mapped[str | None] = mapped_column(sa.String(10))
    local_category: Mapped[str | None] = mapped_column(sa.String(255), index=True)
    weight: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 3))
    is_publishable: Mapped[bool] = mapped_column(default=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )
