"""Domain enumerations.

Stored as plain strings in the database (portable between PostgreSQL and the
SQLite test database); validated at the application layer.
"""
from __future__ import annotations

import enum


class StrEnum(str, enum.Enum):
    def __str__(self) -> str:  # pragma: no cover
        return self.value


class RoleName(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    AUDITOR = "auditor"


class IntegrationProvider(StrEnum):
    """External systems the integrator talks to."""

    FAKTUROWNIA = "FAKTUROWNIA"  # read-only source of truth for sales
    SKYSHOP = "SKYSHOP"          # webshop, the only write direction


class ConfigSource(StrEnum):
    """Where an effective integration configuration came from."""

    DATABASE = "DATABASE"
    ENV = "ENV"
    NONE = "NONE"


class VerificationStatus(StrEnum):
    NEVER = "NEVER"
    OK = "OK"
    FAILED = "FAILED"


class SyncRunType(StrEnum):
    FULL = "FULL"
    INCREMENTAL = "INCREMENTAL"


class SyncRunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ResourceType(StrEnum):
    """Fakturownia resources mirrored locally (all fetched via GET only)."""

    INVOICE = "invoice"
    PRODUCT = "product"
    CLIENT = "client"
    WAREHOUSE = "warehouse"
    WAREHOUSE_DOCUMENT = "warehouse_document"
    WAREHOUSE_ACTION = "warehouse_action"
    CATEGORY = "category"
    DEPARTMENT = "department"
    PAYMENT = "payment"
    PRICE_LIST = "price_list"
    PRODUCT_WAREHOUSE_STOCK = "product_warehouse_stock"


class ProductKind(StrEnum):
    """Local classification of a product for stock control."""

    STOCK_ITEM = "STOCK_ITEM"          # towar magazynowy
    SERVICE = "SERVICE"                # usługa – nie zmienia magazynu
    IGNORED = "IGNORED"                # produkt ignorowany w kontroli
    BUNDLE = "BUNDLE"                  # zestaw / pakiet
    NEEDS_MAPPING = "NEEDS_MAPPING"    # wymaga ręcznej decyzji operatora


class MappingStatus(StrEnum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class MappingMatchType(StrEnum):
    PRODUCT_ID = "PRODUCT_ID"
    CODE = "CODE"
    EAN = "EAN"
    SKU = "SKU"
    NAME = "NAME"
    ALIAS = "ALIAS"
    MANUAL = "MANUAL"


class StockMovementType(StrEnum):
    OPENING_BALANCE = "OPENING_BALANCE"
    SALE = "SALE"
    SALE_CORRECTION = "SALE_CORRECTION"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"
    IMPORTED_WAREHOUSE_ACTION = "IMPORTED_WAREHOUSE_ACTION"


class ValidationRunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class ValidationStatus(StrEnum):
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"
    NEEDS_MAPPING = "NEEDS_MAPPING"
    NEEDS_OPENING_BALANCE = "NEEDS_OPENING_BALANCE"
    IGNORED = "IGNORED"
    RESOLVED = "RESOLVED"


class ValidationIssueType(StrEnum):
    PRODUCT_NOT_RECOGNIZED = "PRODUCT_NOT_RECOGNIZED"
    PRODUCT_ID_MISSING = "PRODUCT_ID_MISSING"
    NEGATIVE_STOCK = "NEGATIVE_STOCK"
    INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    DUPLICATE_INVOICE = "DUPLICATE_INVOICE"
    CANCELLED_INVOICE_INCLUDED = "CANCELLED_INVOICE_INCLUDED"
    CORRECTION_NOT_HANDLED = "CORRECTION_NOT_HANDLED"
    SERVICE_INCLUDED_IN_STOCK = "SERVICE_INCLUDED_IN_STOCK"
    MISSING_OPENING_BALANCE = "MISSING_OPENING_BALANCE"
    STOCK_DISCREPANCY = "STOCK_DISCREPANCY"
    UNKNOWN_DOCUMENT_TYPE = "UNKNOWN_DOCUMENT_TYPE"
    UNKNOWN_PRODUCT_TYPE = "UNKNOWN_PRODUCT_TYPE"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    MAPPING_CONFLICT = "MAPPING_CONFLICT"
    LOCAL_RULE_REQUIRED = "LOCAL_RULE_REQUIRED"
    SALE_BEFORE_OPENING_BALANCE = "SALE_BEFORE_OPENING_BALANCE"
    INACTIVE_PRODUCT_SOLD = "INACTIVE_PRODUCT_SOLD"
    DOUBLE_STOCK_SETTLEMENT = "DOUBLE_STOCK_SETTLEMENT"
    UNKNOWN_UNIT = "UNKNOWN_UNIT"


class IssueSeverity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AuditAction(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    SYNC_STARTED = "SYNC_STARTED"
    SYNC_FINISHED = "SYNC_FINISHED"
    VALIDATION_STARTED = "VALIDATION_STARTED"
    VALIDATION_FINISHED = "VALIDATION_FINISHED"
    STOCK_RECALCULATED = "STOCK_RECALCULATED"
    RECONCILIATION_REFRESHED = "RECONCILIATION_REFRESHED"
    EXPORT = "EXPORT"
    READONLY_VIOLATION_BLOCKED = "READONLY_VIOLATION_BLOCKED"
    INTEGRATION_TESTED = "INTEGRATION_TESTED"
    SKYSHOP_WRITE = "SKYSHOP_WRITE"
    SKYSHOP_WRITE_BLOCKED = "SKYSHOP_WRITE_BLOCKED"
    JOB_ENQUEUED = "JOB_ENQUEUED"


class WarehouseDocumentKind(StrEnum):
    """Warehouse document kinds mirrored from Fakturownia."""

    PZ = "PZ"          # przyjęcie zewnętrzne (goods receipt from a supplier)
    PW = "PW"          # przyjęcie wewnętrzne (internal receipt)
    WZ = "WZ"          # wydanie zewnętrzne
    RW = "RW"          # rozchód wewnętrzny
    MM = "MM"          # przesunięcie międzymagazynowe
    ZW = "ZW"          # zwrot
    OTHER = "OTHER"


INBOUND_DOCUMENT_KINDS = (WarehouseDocumentKind.PZ, WarehouseDocumentKind.PW)


class ReconciliationStatus(StrEnum):
    OK = "OK"
    DISCREPANCY = "DISCREPANCY"
    NO_REMOTE_STOCK = "NO_REMOTE_STOCK"


class SkyShopLinkStatus(StrEnum):
    LINKED = "LINKED"
    MISSING = "MISSING"
    AMBIGUOUS = "AMBIGUOUS"
    EXCLUDED = "EXCLUDED"
    PENDING_CREATE = "PENDING_CREATE"


class SyncJobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


class SyncJobType(StrEnum):
    SKYSHOP_STOCK_PUSH = "SKYSHOP_STOCK_PUSH"
    SKYSHOP_PRODUCT_CREATE = "SKYSHOP_PRODUCT_CREATE"
    SKYSHOP_PRODUCT_UPDATE = "SKYSHOP_PRODUCT_UPDATE"
    SKYSHOP_MIRROR_REFRESH = "SKYSHOP_MIRROR_REFRESH"


class StockSource(StrEnum):
    """Which stock figure is published to the webshop."""

    LOCAL_LEDGER = "LOCAL_LEDGER"
    FAKTUROWNIA = "FAKTUROWNIA"
    RECONCILED = "RECONCILED"


class ExportFormat(StrEnum):
    CSV = "CSV"
    XLSX = "XLSX"
    PDF = "PDF"
