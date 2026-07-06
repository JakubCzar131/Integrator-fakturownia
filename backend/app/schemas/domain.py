"""API schemas for domain resources."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


# ------------------------------ sync ---------------------------------- #
class SyncRunOut(ORMModel):
    id: int
    run_type: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    records_fetched: int
    records_created: int
    records_updated: int
    records_unchanged: int
    error_count: int
    stats: dict[str, Any] | None = None
    errors: list[Any] | None = None
    message: str | None = None


# ---------------------------- invoices -------------------------------- #
class InvoicePositionOut(ORMModel):
    id: int
    fakturownia_id: int | None = None
    invoice_id: int
    invoice_fakturownia_id: int | None = None
    product_fakturownia_id: int | None = None
    name: str | None = None
    code: str | None = None
    quantity: Decimal | None = None
    quantity_unit: str | None = None
    price_net: Decimal | None = None
    price_gross: Decimal | None = None
    total_price_net: Decimal | None = None
    total_price_gross: Decimal | None = None
    tax: str | None = None
    mapped_product_id: int | None = None
    mapping_status: str | None = None
    mapping_match_type: str | None = None


class InvoicePositionListItem(InvoicePositionOut):
    invoice_number: str | None = None
    invoice_issue_date: date | None = None
    invoice_kind: str | None = None
    buyer_name: str | None = None
    open_issue_count: int = 0


class InvoiceOut(ORMModel):
    id: int
    fakturownia_id: int
    number: str | None = None
    kind: str | None = None
    invoice_status: str | None = None
    issue_date: date | None = None
    sell_date: date | None = None
    client_fakturownia_id: int | None = None
    buyer_name: str | None = None
    buyer_tax_no: str | None = None
    warehouse_fakturownia_id: int | None = None
    currency: str | None = None
    total_net: Decimal | None = None
    total_gross: Decimal | None = None
    paid_amount: Decimal | None = None
    is_correction: bool
    corrected_invoice_fakturownia_id: int | None = None
    is_cancelled: bool
    is_deleted_upstream: bool
    last_synced_at: datetime | None = None
    open_issue_count: int = 0
    position_count: int = 0


class InvoiceDetailOut(InvoiceOut):
    positions: list[InvoicePositionOut] = []
    raw: dict[str, Any] | None = None


# ---------------------------- products -------------------------------- #
class ProductAliasOut(ORMModel):
    id: int
    product_id: int
    alias_type: str
    alias_value: str
    created_at: datetime


class BundleComponentOut(ORMModel):
    id: int
    component_product_id: int
    quantity: Decimal
    component_name: str | None = None


class ProductOut(ORMModel):
    id: int
    fakturownia_product_id: int | None = None
    name: str
    code: str | None = None
    ean: str | None = None
    sku: str | None = None
    unit: str | None = None
    kind: str
    is_stock_controlled: bool
    is_active: bool
    notes: str | None = None
    total_local_stock: Decimal | None = None
    fakturownia_quantity: Decimal | None = None
    open_issue_count: int = 0


class ProductDetailOut(ProductOut):
    aliases: list[ProductAliasOut] = []
    bundle_components: list[BundleComponentOut] = []


class ProductUpdate(BaseModel):
    kind: str | None = None
    is_stock_controlled: bool | None = None
    is_active: bool | None = None
    unit: str | None = None
    notes: str | None = None


class ProductAliasCreate(BaseModel):
    product_id: int
    alias_type: str = Field(pattern="^(NAME|CODE|EAN|SKU|UNIT)$")
    alias_value: str = Field(min_length=1)


class BundleComponentCreate(BaseModel):
    component_product_id: int
    quantity: Decimal = Decimal("1")


# ---------------------------- mappings -------------------------------- #
class ProductMappingOut(ORMModel):
    id: int
    source_name: str | None = None
    source_code: str | None = None
    source_ean: str | None = None
    source_unit: str | None = None
    product_id: int | None = None
    product_name: str | None = None
    match_type: str
    status: str
    confidence: Decimal | None = None
    notes: str | None = None
    created_at: datetime
    confirmed_at: datetime | None = None
    occurrence_count: int = 0


class ProductMappingCreate(BaseModel):
    source_name: str | None = None
    source_code: str | None = None
    source_ean: str | None = None
    source_unit: str | None = None
    product_id: int
    notes: str | None = None


class ProductMappingUpdate(BaseModel):
    product_id: int | None = None
    status: str | None = Field(default=None, pattern="^(PROPOSED|CONFIRMED|REJECTED)$")
    notes: str | None = None


# ---------------------------- warehouses / stock ----------------------- #
class WarehouseOut(ORMModel):
    id: int
    fakturownia_id: int | None = None
    name: str
    kind: str | None = None
    description: str | None = None
    is_default: bool
    product_count: int = 0
    negative_count: int = 0


class StockBalanceOut(ORMModel):
    id: int
    product_id: int
    warehouse_id: int
    quantity: Decimal
    last_movement_at: datetime | None = None
    last_sale_at: datetime | None = None
    recalculated_at: datetime | None = None
    product_name: str | None = None
    product_code: str | None = None
    product_unit: str | None = None
    warehouse_name: str | None = None
    fakturownia_quantity: Decimal | None = None
    difference: Decimal | None = None


class StockLedgerEntryOut(ORMModel):
    id: int
    product_id: int
    warehouse_id: int
    movement_type: str
    quantity_change: Decimal
    balance_before: Decimal
    balance_after: Decimal
    occurred_at: datetime
    sequence: int
    source_invoice_id: int | None = None
    source_invoice_position_id: int | None = None
    source_adjustment_id: int | None = None
    source_opening_balance_id: int | None = None
    source_warehouse_action_id: int | None = None
    description: str | None = None
    created_by_user_id: int | None = None
    product_name: str | None = None
    warehouse_name: str | None = None
    invoice_number: str | None = None


class OpeningBalanceCreate(BaseModel):
    product_id: int
    warehouse_id: int
    quantity: Decimal
    as_of_date: date
    note: str | None = None


class OpeningBalanceOut(ORMModel):
    id: int
    product_id: int
    warehouse_id: int
    quantity: Decimal
    as_of_date: date
    note: str | None = None
    created_by_user_id: int | None = None
    created_at: datetime
    product_name: str | None = None
    warehouse_name: str | None = None


class StockAdjustmentCreate(BaseModel):
    product_id: int
    warehouse_id: int
    quantity_change: Decimal
    description: str = Field(min_length=3)
    occurred_at: datetime | None = None


class StockAdjustmentOut(ORMModel):
    id: int
    product_id: int
    warehouse_id: int
    quantity_change: Decimal
    description: str
    occurred_at: datetime
    is_reversal: bool
    reverses_adjustment_id: int | None = None
    created_by_user_id: int | None = None
    created_at: datetime
    product_name: str | None = None
    warehouse_name: str | None = None


# ---------------------------- validation ------------------------------- #
class ValidationRunOut(ORMModel):
    id: int
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    invoices_checked: int
    positions_checked: int
    issues_created: int
    issues_auto_resolved: int
    message: str | None = None
    stats: dict[str, Any] | None = None


class IssueCommentOut(ORMModel):
    id: int
    issue_id: int
    user_id: int | None = None
    user_email: str | None = None
    body: str
    created_at: datetime


class ValidationIssueOut(ORMModel):
    id: int
    validation_run_id: int | None = None
    issue_type: str
    status: str
    severity: str
    invoice_id: int | None = None
    invoice_position_id: int | None = None
    product_id: int | None = None
    warehouse_id: int | None = None
    quantity: Decimal | None = None
    stock_before: Decimal | None = None
    stock_after: Decimal | None = None
    technical_description: str | None = None
    business_description: str | None = None
    recommended_action: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    resolved_at: datetime | None = None
    resolved_by_user_id: int | None = None
    invoice_number: str | None = None
    product_name: str | None = None
    warehouse_name: str | None = None
    comments: list[IssueCommentOut] = []


class ValidationIssueUpdate(BaseModel):
    status: str = Field(
        pattern="^(OK|WARNING|ERROR|NEEDS_MAPPING|NEEDS_OPENING_BALANCE|IGNORED|RESOLVED)$"
    )


class IssueCommentCreate(BaseModel):
    body: str = Field(min_length=1)


# ---------------------------- misc ------------------------------------- #
class AuditLogOut(ORMModel):
    id: int
    user_id: int | None = None
    user_email: str | None = None
    action: str
    object_type: str | None = None
    object_id: str | None = None
    description: str | None = None
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    ip_address: str | None = None
    created_at: datetime


class AppSettingOut(ORMModel):
    key: str
    value: Any | None = None
    description: str | None = None
    updated_at: datetime | None = None


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


class ColumnPreferenceIn(BaseModel):
    table_key: str
    columns: dict[str, Any]


class FakturowniaClientOut(ORMModel):
    id: int
    fakturownia_id: int
    name: str | None = None
    tax_no: str | None = None
    email: str | None = None
    phone: str | None = None
    city: str | None = None
    street: str | None = None
    post_code: str | None = None
    country: str | None = None
    is_deleted_upstream: bool


class DashboardOut(BaseModel):
    last_sync: SyncRunOut | None = None
    last_validation: ValidationRunOut | None = None
    invoice_count: int = 0
    position_count: int = 0
    product_count: int = 0
    client_count: int = 0
    warehouse_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    needs_mapping_count: int = 0
    needs_opening_balance_count: int = 0
    unmapped_position_count: int = 0
    negative_stock_count: int = 0
    invoices_needing_attention: list[dict[str, Any]] = []
    issue_type_breakdown: list[dict[str, Any]] = []
