"""API schemas for integration accounts, reconciliation, SkyShop and PIM.

Secrets are strictly one-way: they can be *sent* to the API when configuring an
account, but no response model contains a token — only ``secret_configured``
and a four-character ``secret_hint``.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

PROVIDER_PATTERN = "^(FAKTUROWNIA|SKYSHOP)$"


# ----------------------- integration accounts -------------------------- #
class IntegrationAccountOut(ORMModel):
    id: int
    provider: str
    label: str
    config: dict[str, Any] = {}
    secret_configured: bool = False
    secret_hint: str | None = None
    is_active: bool
    verified_at: datetime | None = None
    verified_status: str
    verified_error: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    is_effective: bool = False


class IntegrationAccountCreate(BaseModel):
    provider: str = Field(pattern=PROVIDER_PATTERN)
    label: str = Field(min_length=1, max_length=255)
    config: dict[str, Any] = Field(default_factory=dict)
    secret: str | None = Field(default=None, min_length=4)
    is_active: bool = True


class IntegrationAccountUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=255)
    config: dict[str, Any] | None = None
    # Empty / omitted keeps the stored secret untouched.
    secret: str | None = Field(default=None, min_length=4)
    is_active: bool | None = None


class EffectiveIntegrationOut(BaseModel):
    """What the application would actually use right now."""

    provider: str
    source: str  # DATABASE | ENV | NONE
    is_configured: bool
    label: str | None = None
    account_id: int | None = None
    target: str | None = None  # base URL / shop address, never a secret
    details: dict[str, Any] = {}


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str
    detail: dict[str, Any] | None = None


# --------------------------- reconciliation ---------------------------- #
class ReconciliationRunOut(ORMModel):
    id: int
    started_at: datetime
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    trigger: str
    sync_run_id: int | None = None
    line_count: int
    discrepancy_count: int
    tolerance: Decimal | None = None
    stats: dict[str, Any] | None = None
    triggered_by_user_id: int | None = None


class ReconciliationLineOut(ORMModel):
    id: int
    run_id: int
    product_id: int
    warehouse_id: int | None = None
    fakturownia_stock: Decimal | None = None
    inbound_pz: Decimal
    inbound_pw: Decimal
    outbound_documents: Decimal
    sold_invoices: Decimal
    corrections: Decimal
    opening_balance: Decimal | None = None
    local_ledger_stock: Decimal | None = None
    computed_stock: Decimal
    difference: Decimal | None = None
    status: str
    computed_at: datetime
    product_name: str | None = None
    product_code: str | None = None
    product_unit: str | None = None
    warehouse_name: str | None = None


# ------------------------ warehouse documents -------------------------- #
class WarehouseDocumentPositionOut(ORMModel):
    id: int
    document_id: int
    document_kind: str | None = None
    fakturownia_id: int | None = None
    product_fakturownia_id: int | None = None
    mapped_product_id: int | None = None
    mapping_status: str | None = None
    mapping_match_type: str | None = None
    name: str | None = None
    code: str | None = None
    quantity: Decimal | None = None
    quantity_unit: str | None = None
    purchase_price_net: Decimal | None = None
    issue_date: date | None = None
    warehouse_fakturownia_id: int | None = None
    product_name: str | None = None
    document_number: str | None = None


class WarehouseDocumentOut(ORMModel):
    id: int
    fakturownia_id: int
    kind: str | None = None
    number: str | None = None
    warehouse_fakturownia_id: int | None = None
    issue_date: date | None = None
    client_fakturownia_id: int | None = None
    invoice_fakturownia_id: int | None = None
    description: str | None = None
    is_deleted_upstream: bool
    last_synced_at: datetime | None = None
    warehouse_name: str | None = None
    position_count: int = 0
    total_quantity: Decimal | None = None
    unmapped_position_count: int = 0


class WarehouseDocumentDetailOut(WarehouseDocumentOut):
    positions: list[WarehouseDocumentPositionOut] = []
    raw: dict[str, Any] | None = None


# ------------------------------ SkyShop -------------------------------- #
class SkyShopLinkOut(ORMModel):
    id: int
    product_id: int
    skyshop_id: str | None = None
    status: str
    match_type: str | None = None
    candidate_skyshop_ids: list[Any] | None = None
    last_pushed_stock: Decimal | None = None
    last_pushed_content_hash: str | None = None
    last_pushed_at: datetime | None = None
    last_error: str | None = None
    notes: str | None = None
    updated_at: datetime | None = None
    product_name: str | None = None
    product_code: str | None = None
    product_sku: str | None = None
    product_ean: str | None = None
    local_stock: Decimal | None = None
    shop_stock: Decimal | None = None
    shop_name: str | None = None
    stock_out_of_sync: bool = False
    content_out_of_sync: bool = False
    publication_problems: list[str] = []


class SkyShopLinkUpdate(BaseModel):
    skyshop_id: str | None = None
    status: str | None = Field(
        default=None, pattern="^(LINKED|MISSING|AMBIGUOUS|EXCLUDED|PENDING_CREATE)$"
    )
    notes: str | None = None


class SkyShopProductOut(ORMModel):
    id: int
    skyshop_id: str
    sku: str | None = None
    ean: str | None = None
    name: str | None = None
    price_gross: Decimal | None = None
    quantity: Decimal | None = None
    category_skyshop_id: str | None = None
    is_active: bool | None = None
    is_deleted_upstream: bool
    last_synced_at: datetime | None = None


class SkyShopCategoryOut(ORMModel):
    id: int
    skyshop_id: str
    name: str | None = None
    parent_skyshop_id: str | None = None
    path: str | None = None
    mapped_local_category: str | None = None


class SkyShopCategoryMappingIn(BaseModel):
    local_category: str = Field(min_length=1, max_length=255)
    skyshop_category_id: str = Field(min_length=1, max_length=64)


class SkyShopCategoryMappingOut(ORMModel):
    id: int
    local_category: str
    skyshop_category_id: str
    skyshop_category_name: str | None = None
    updated_at: datetime | None = None


class ProductPushRequest(BaseModel):
    product_ids: list[int] = Field(min_length=1)
    mode: str = Field(default="auto", pattern="^(auto|create|update)$")
    force: bool = False


class StockSyncRequest(BaseModel):
    product_ids: list[int] | None = None
    force: bool = False


class ProductContentOut(ORMModel):
    product_id: int
    description_html: str | None = None
    short_description: str | None = None
    images: list[Any] = []
    attributes: dict[str, Any] = {}
    price_gross: Decimal | None = None
    vat_rate: str | None = None
    local_category: str | None = None
    weight: Decimal | None = None
    is_publishable: bool = True
    updated_at: datetime | None = None
    content_hash: str | None = None
    publication_problems: list[str] = []


class ProductContentIn(BaseModel):
    description_html: str | None = None
    short_description: str | None = None
    images: list[Any] | None = None
    attributes: dict[str, Any] | None = None
    price_gross: Decimal | None = None
    vat_rate: str | None = None
    local_category: str | None = None
    weight: Decimal | None = None
    is_publishable: bool | None = None


class SyncJobOut(ORMModel):
    id: int
    provider: str
    job_type: str
    dedupe_key: str | None = None
    payload: dict[str, Any] = {}
    status: str
    priority: int
    attempts: int
    max_attempts: int
    next_attempt_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, Any] | None = None
    last_error: str | None = None
    product_id: int | None = None
    created_at: datetime
    product_name: str | None = None
