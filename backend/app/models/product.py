"""Local product master data, aliases, mappings and bundles.

The local ``products`` table is the authoritative catalogue for stock control.
Products are usually created automatically from ``fakturownia_products`` during
sync, but operators can adjust their local classification (stock item /
service / ignored / bundle) without ever touching Fakturownia.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

Qty = sa.Numeric(18, 4)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    fakturownia_product_id: Mapped[int | None] = mapped_column(
        sa.BigInteger, unique=True, index=True
    )
    name: Mapped[str] = mapped_column(sa.String(500), index=True)
    code: Mapped[str | None] = mapped_column(sa.String(255), index=True)
    ean: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    sku: Mapped[str | None] = mapped_column(sa.String(255), index=True)
    unit: Mapped[str | None] = mapped_column(sa.String(50))
    kind: Mapped[str] = mapped_column(sa.String(20), default="STOCK_ITEM", index=True)
    is_stock_controlled: Mapped[bool] = mapped_column(default=True, index=True)
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    aliases: Mapped[list["ProductAlias"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", lazy="selectin"
    )
    bundle_components: Mapped[list["ProductBundleComponent"]] = relationship(
        back_populates="bundle",
        foreign_keys="ProductBundleComponent.bundle_product_id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ProductAlias(Base):
    """Alternative identifier (name / code / EAN / SKU / unit) pointing at a local product."""

    __tablename__ = "product_aliases"
    __table_args__ = (
        sa.UniqueConstraint("alias_type", "alias_value_normalized",
                            name="uq_product_aliases_type_value"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        sa.ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    alias_type: Mapped[str] = mapped_column(sa.String(20))  # NAME | CODE | EAN | SKU | UNIT
    alias_value: Mapped[str] = mapped_column(sa.String(1000))
    alias_value_normalized: Mapped[str] = mapped_column(sa.String(1000), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    product: Mapped[Product] = relationship(back_populates="aliases")


class ProductMapping(Base):
    """Mapping of an unrecognized invoice-position signature to a local product.

    A mapping is keyed by the *source signature* (name / code / EAN / unit as
    they appear on invoice positions), so a confirmed mapping automatically
    applies to every past and future position with the same signature.
    """

    __tablename__ = "product_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_name: Mapped[str | None] = mapped_column(sa.String(1000), index=True)
    source_code: Mapped[str | None] = mapped_column(sa.String(255), index=True)
    source_ean: Mapped[str | None] = mapped_column(sa.String(64))
    source_unit: Mapped[str | None] = mapped_column(sa.String(50))
    signature: Mapped[str] = mapped_column(sa.String(64), index=True)  # sha256 of normalized source fields
    product_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    match_type: Mapped[str] = mapped_column(sa.String(20), default="MANUAL")
    status: Mapped[str] = mapped_column(sa.String(20), default="PROPOSED", index=True)
    confidence: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 2))
    example_invoice_position_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("fakturownia_invoice_positions.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(sa.Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    product: Mapped[Product | None] = relationship()


class ProductBundleComponent(Base):
    """Locally defined bundle/kit composition (never pushed to Fakturownia)."""

    __tablename__ = "product_bundle_components"
    __table_args__ = (
        sa.UniqueConstraint("bundle_product_id", "component_product_id",
                            name="uq_bundle_component"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bundle_product_id: Mapped[int] = mapped_column(
        sa.ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    component_product_id: Mapped[int] = mapped_column(
        sa.ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Qty, default=Decimal("1"))

    bundle: Mapped[Product] = relationship(
        back_populates="bundle_components", foreign_keys=[bundle_product_id]
    )
    component: Mapped[Product] = relationship(foreign_keys=[component_product_id])
