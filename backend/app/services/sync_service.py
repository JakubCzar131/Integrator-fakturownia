"""Synchronization of Fakturownia data into the local mirror tables.

All communication goes through the GET-only :class:`FakturowniaClient`.
The sync is idempotent: every record is upserted by its ``fakturownia_id``
and unchanged payloads (verified by SHA-256 hash) are skipped, so re-running
a sync never duplicates data.

Raw JSON payloads are stored in ``source_snapshots`` whenever a record is new
or has changed, giving a complete audit trail of what the source system
returned over time.

Deletion detection: during a FULL sync every mirrored id that is no longer
returned by the API is flagged ``is_deleted_upstream`` (rows are never
physically removed locally).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import (
    IntegrationProvider,
    ResourceType,
    SyncRunStatus,
    SyncRunType,
)
from app.models.fakturownia import (
    FakturowniaCategory,
    FakturowniaClient as FakturowniaClientRow,
    FakturowniaDepartment,
    FakturowniaInvoice,
    FakturowniaInvoicePosition,
    FakturowniaPayment,
    FakturowniaPriceList,
    FakturowniaProduct,
    FakturowniaProductStock,
    Warehouse,
    WarehouseAction,
    WarehouseDocument,
)
from app.models.settings import AppSetting
from app.models.sync import SourceSnapshot, SyncRun
from app.models.user import User
from app.services import parsing as p
from app.services.fakturownia_client import FakturowniaClient, FakturowniaError
from app.services.mapping_service import (
    apply_document_position_mappings,
    apply_position_mappings,
    ensure_local_products,
)
from app.services.reconciliation_service import ReconciliationService
from app.services.stock_service import StockService, get_setting
from app.services.warehouse_document_service import rebuild_document_positions

logger = logging.getLogger(__name__)

LAST_SYNC_SETTING_KEY = "last_successful_sync_at"
INCREMENTAL_OVERLAP_DAYS = 7

SETTING_REBUILD_STOCK_AFTER_SYNC = "sync_rebuild_stock_after_sync"
SETTING_RECONCILE_AFTER_SYNC = "sync_reconcile_after_sync"


@dataclass
class ResourceCounters:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "fetched": self.fetched,
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "errors": self.errors,
        }


class SyncService:
    def __init__(self, db: Session, client: FakturowniaClient) -> None:
        self.db = db
        self.client = client

    # ------------------------------------------------------------------ #
    # Public entry points
    # ------------------------------------------------------------------ #
    def run_full_sync(self, user: User | None = None) -> SyncRun:
        return self._run(SyncRunType.FULL, user)

    def run_incremental_sync(self, user: User | None = None) -> SyncRun:
        return self._run(SyncRunType.INCREMENTAL, user)

    def _run(self, run_type: SyncRunType, user: User | None) -> SyncRun:
        run = SyncRun(
            provider=str(IntegrationProvider.FAKTUROWNIA),
            run_type=str(run_type),
            status=str(SyncRunStatus.RUNNING),
            triggered_by_user_id=user.id if user else None,
        )
        self.db.add(run)
        self.db.commit()

        started = datetime.now(timezone.utc)
        stats: dict[str, Any] = {}
        all_errors: list[str] = []
        full = run_type == SyncRunType.FULL

        steps: list[tuple[str, Callable[[SyncRun, bool], ResourceCounters]]] = [
            ("departments", self._sync_departments),
            ("categories", self._sync_categories),
            ("warehouses", self._sync_warehouses),
            ("products", self._sync_products),
            ("product_warehouse_stocks", self._sync_product_warehouse_stocks),
            ("clients", self._sync_clients),
            ("invoices", self._sync_invoices),
            ("warehouse_documents", self._sync_warehouse_documents),
            ("warehouse_actions", self._sync_warehouse_actions),
            ("payments", self._sync_payments),
            ("price_lists", self._sync_price_lists),
        ]

        for name, step in steps:
            try:
                counters = step(run, full)
                stats[name] = counters.as_dict()
                run.records_fetched += counters.fetched
                run.records_created += counters.created
                run.records_updated += counters.updated
                run.records_unchanged += counters.unchanged
                all_errors.extend(f"{name}: {e}" for e in counters.errors)
                self.db.commit()
            except FakturowniaError as exc:
                self.db.rollback()
                message = f"{name}: {exc}"
                logger.error("Sync step failed: %s", message)
                all_errors.append(message)
            except Exception as exc:  # unexpected — keep other steps running
                self.db.rollback()
                message = f"{name}: unexpected error: {exc}"
                logger.exception("Sync step crashed: %s", name)
                all_errors.append(message)

        # Post-processing (local only): product master, position mapping,
        # normalized PZ/PW positions.
        try:
            ensure_local_products(self.db)
            stats["position_mapping"] = apply_position_mappings(self.db)
            stats["warehouse_document_positions"] = rebuild_document_positions(self.db)
            stats["document_position_mapping"] = apply_document_position_mappings(self.db)
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            all_errors.append(f"post_processing: {exc}")
            logger.exception("Sync post-processing failed")

        # Derived layers: ledger rebuild, reconciliation snapshot and the
        # SkyShop stock delta (queued, never sent inline).
        for name, step_fn in (
            ("stock_rebuild", self._rebuild_stock_step),
            ("reconciliation", lambda: self._reconciliation_step(run)),
            ("skyshop_stock_delta", self._skyshop_delta_step),
        ):
            try:
                result = step_fn()
                if result is not None:
                    stats[name] = result
                self.db.commit()
            except Exception as exc:
                self.db.rollback()
                all_errors.append(f"{name}: {exc}")
                logger.exception("Sync follow-up step failed: %s", name)

        finished = datetime.now(timezone.utc)
        run.finished_at = finished
        run.duration_seconds = (finished - started).total_seconds()
        run.stats = stats
        run.errors = all_errors or None
        run.error_count = len(all_errors)
        if not all_errors:
            run.status = str(SyncRunStatus.SUCCESS)
            self._store_last_sync_timestamp(finished)
        elif run.records_fetched > 0:
            run.status = str(SyncRunStatus.PARTIAL)
        else:
            run.status = str(SyncRunStatus.FAILED)
        run.message = (
            "Synchronizacja zakończona pomyślnie"
            if not all_errors
            else f"Zakończono z {len(all_errors)} błędami"
        )
        self.db.commit()
        return run

    # ------------------------------------------------------------------ #
    # Follow-up steps (all local; the SkyShop push is only enqueued)
    # ------------------------------------------------------------------ #
    def _rebuild_stock_step(self) -> dict[str, Any] | None:
        if not get_setting(self.db, SETTING_REBUILD_STOCK_AFTER_SYNC, True):
            return None
        return StockService(self.db).rebuild_stock()

    def _reconciliation_step(self, run: SyncRun) -> dict[str, Any] | None:
        if not get_setting(self.db, SETTING_RECONCILE_AFTER_SYNC, True):
            return None
        reconciliation = ReconciliationService(self.db).refresh(
            trigger="SYNC", sync_run_id=run.id
        )
        return {
            "run_id": reconciliation.id,
            "lines": reconciliation.line_count,
            "discrepancies": reconciliation.discrepancy_count,
        }

    def _skyshop_delta_step(self) -> dict[str, Any] | None:
        """Queue stock pushes for products whose quantity changed.

        Only enqueues — the outbox worker performs the actual (rate-limited)
        requests, and the global kill switch still applies at execution time.
        """
        from app.services.skyshop_service import SETTING_AUTO_STOCK_PUSH, SkyShopService

        if not get_setting(self.db, SETTING_AUTO_STOCK_PUSH, False):
            return None
        return SkyShopService(self.db).enqueue_stock_sync()

    # ------------------------------------------------------------------ #
    # Generic upsert helpers
    # ------------------------------------------------------------------ #
    def _store_snapshot(
        self, run: SyncRun, resource_type: ResourceType, external_id: int | None,
        payload: dict[str, Any], content_hash: str,
    ) -> None:
        self.db.add(
            SourceSnapshot(
                sync_run_id=run.id,
                resource_type=str(resource_type),
                external_id=external_id,
                payload=payload,
                payload_hash=content_hash,
            )
        )

    def _upsert(
        self,
        run: SyncRun,
        model: type,
        resource_type: ResourceType,
        payload: dict[str, Any],
        fields: dict[str, Any],
        counters: ResourceCounters,
        seen_ids: set[int] | None,
    ) -> Any:
        fakturownia_id = p.to_int(payload.get("id"))
        if fakturownia_id is None:
            counters.errors.append(f"record without id in {resource_type}")
            return None
        if seen_ids is not None:
            seen_ids.add(fakturownia_id)
        counters.fetched += 1

        content_hash = p.payload_hash(payload)
        row = self.db.execute(
            select(model).where(model.fakturownia_id == fakturownia_id)
        ).scalar_one_or_none()

        if row is not None and row.payload_hash == content_hash:
            counters.unchanged += 1
            row.last_synced_at = datetime.now(timezone.utc)
            row.is_deleted_upstream = False
            return row

        self._store_snapshot(run, resource_type, fakturownia_id, payload, content_hash)

        if row is None:
            row = model(fakturownia_id=fakturownia_id)
            self.db.add(row)
            counters.created += 1
        else:
            counters.updated += 1

        for key, value in fields.items():
            setattr(row, key, value)
        row.raw = payload
        row.payload_hash = content_hash
        row.is_deleted_upstream = False
        row.last_synced_at = datetime.now(timezone.utc)
        return row

    def _mark_deleted(self, model: type, seen_ids: set[int], counters: ResourceCounters) -> None:
        """FULL sync only: flag mirrored rows that upstream no longer returns."""
        rows = self.db.execute(
            select(model).where(model.is_deleted_upstream.is_(False))
        ).scalars()
        for row in rows:
            if row.fakturownia_id is not None and row.fakturownia_id not in seen_ids:
                row.is_deleted_upstream = True
                counters.updated += 1

    # ------------------------------------------------------------------ #
    # Resource steps
    # ------------------------------------------------------------------ #
    def _sync_departments(self, run: SyncRun, full: bool) -> ResourceCounters:
        counters = ResourceCounters()
        seen: set[int] = set()
        for item in self.client.get_departments():
            self._upsert(
                run, FakturowniaDepartment, ResourceType.DEPARTMENT, item,
                {
                    "name": p.to_str(item.get("name"), 500),
                    "shortcut": p.to_str(item.get("shortcut"), 100),
                },
                counters, seen,
            )
        if full:
            self._mark_deleted(FakturowniaDepartment, seen, counters)
        return counters

    def _sync_categories(self, run: SyncRun, full: bool) -> ResourceCounters:
        counters = ResourceCounters()
        seen: set[int] = set()
        for item in self.client.get_categories():
            self._upsert(
                run, FakturowniaCategory, ResourceType.CATEGORY, item,
                {
                    "name": p.to_str(item.get("name"), 255),
                    "description": p.to_str(item.get("description")),
                },
                counters, seen,
            )
        if full:
            self._mark_deleted(FakturowniaCategory, seen, counters)
        return counters

    def _sync_warehouses(self, run: SyncRun, full: bool) -> ResourceCounters:
        counters = ResourceCounters()
        seen: set[int] = set()
        for item in self.client.get_warehouses():
            self._upsert(
                run, Warehouse, ResourceType.WAREHOUSE, item,
                {
                    "name": p.to_str(item.get("name"), 255) or f"Magazyn {item.get('id')}",
                    "kind": p.to_str(item.get("kind"), 50),
                    "description": p.to_str(item.get("description")),
                },
                counters, seen,
            )
        if full:
            self._mark_deleted(Warehouse, seen, counters)
        self.db.flush()
        self._ensure_default_warehouse()
        return counters

    def _ensure_default_warehouse(self) -> None:
        existing = self.db.execute(select(Warehouse)).scalars().first()
        if existing is None:
            self.db.add(
                Warehouse(
                    fakturownia_id=None,
                    name="Magazyn główny (lokalny)",
                    kind="local",
                    description="Domyślny magazyn lokalny utworzony automatycznie "
                                "(Fakturownia nie udostępnia magazynów).",
                    is_default=True,
                )
            )
        elif not self.db.execute(
            select(Warehouse).where(Warehouse.is_default.is_(True))
        ).scalars().first():
            existing.is_default = True

    def _sync_products(self, run: SyncRun, full: bool) -> ResourceCounters:
        counters = ResourceCounters()
        seen: set[int] = set()
        for page in self.client.iter_products():
            for item in page:
                self._upsert(
                    run, FakturowniaProduct, ResourceType.PRODUCT, item,
                    {
                        "name": p.to_str(item.get("name"), 500),
                        "code": p.to_str(item.get("code"), 255),
                        "ean": p.to_str(item.get("ean_code") or item.get("ean"), 64),
                        "sku": p.to_str(item.get("sku") or item.get("additional_info"), 255),
                        "unit": p.to_str(item.get("quantity_unit") or item.get("unit"), 50),
                        "tax": p.to_str(item.get("tax"), 20),
                        "price_net": p.to_decimal(item.get("price_net")),
                        "price_gross": p.to_decimal(item.get("price_gross")),
                        "currency": p.to_str(item.get("currency"), 10),
                        "category_fakturownia_id": p.to_int(item.get("category_id")),
                        "quantity": p.to_decimal(item.get("quantity")),
                        "is_service_upstream": (
                            p.to_bool(item.get("service")) if "service" in item else None
                        ),
                        "disabled": p.to_bool(item.get("disabled")),
                    },
                    counters, seen,
                )
            self.db.flush()
        if full:
            self._mark_deleted(FakturowniaProduct, seen, counters)
        return counters

    def _sync_product_warehouse_stocks(self, run: SyncRun, full: bool) -> ResourceCounters:
        """Per-warehouse stock levels reported by Fakturownia (if warehouses exist)."""
        counters = ResourceCounters()
        warehouses = self.db.execute(
            select(Warehouse).where(Warehouse.fakturownia_id.isnot(None))
        ).scalars().all()
        for warehouse in warehouses:
            for page in self.client.iter_products(warehouse_id=warehouse.fakturownia_id):
                for item in page:
                    product_fid = p.to_int(item.get("id"))
                    if product_fid is None:
                        continue
                    counters.fetched += 1
                    quantity = p.to_decimal(item.get("quantity"))
                    row = self.db.execute(
                        select(FakturowniaProductStock).where(
                            FakturowniaProductStock.product_fakturownia_id == product_fid,
                            FakturowniaProductStock.warehouse_fakturownia_id
                            == warehouse.fakturownia_id,
                        )
                    ).scalar_one_or_none()
                    if row is None:
                        row = FakturowniaProductStock(
                            product_fakturownia_id=product_fid,
                            warehouse_fakturownia_id=warehouse.fakturownia_id,
                        )
                        self.db.add(row)
                        counters.created += 1
                    elif row.quantity == quantity:
                        counters.unchanged += 1
                    else:
                        counters.updated += 1
                    row.quantity = quantity
                    row.fetched_at = datetime.now(timezone.utc)
                self.db.flush()
        return counters

    def _sync_clients(self, run: SyncRun, full: bool) -> ResourceCounters:
        counters = ResourceCounters()
        seen: set[int] = set()
        for page in self.client.iter_clients():
            for item in page:
                self._upsert(
                    run, FakturowniaClientRow, ResourceType.CLIENT, item,
                    {
                        "name": p.to_str(item.get("name"), 500),
                        "tax_no": p.to_str(item.get("tax_no"), 50),
                        "email": p.to_str(item.get("email"), 255),
                        "phone": p.to_str(item.get("phone"), 100),
                        "street": p.to_str(item.get("street"), 255),
                        "city": p.to_str(item.get("city"), 255),
                        "post_code": p.to_str(item.get("post_code"), 20),
                        "country": p.to_str(item.get("country"), 100),
                    },
                    counters, seen,
                )
            self.db.flush()
        if full:
            self._mark_deleted(FakturowniaClientRow, seen, counters)
        return counters

    def _sync_invoices(self, run: SyncRun, full: bool) -> ResourceCounters:
        counters = ResourceCounters()
        seen: set[int] = set()
        if full:
            pages = self.client.iter_invoices(period="all")
        else:
            date_from = self._incremental_date_from()
            pages = self.client.iter_invoices(
                period="more",
                date_from=date_from.isoformat(),
                date_to=date.today().isoformat(),
            )
        for page in pages:
            for item in page:
                self._upsert_invoice(run, item, counters, seen)
            self.db.flush()
        if full:
            self._mark_deleted(FakturowniaInvoice, seen, counters)
        return counters

    def _upsert_invoice(
        self, run: SyncRun, item: dict[str, Any], counters: ResourceCounters, seen: set[int]
    ) -> None:
        kind = p.to_str(item.get("kind"), 50)
        status = p.to_str(item.get("status"), 50)
        is_cancelled = (
            p.to_bool(item.get("cancelled"))
            or status in ("cancelled", "canceled")
            or kind == "cancelled"
        )
        invoice = self._upsert(
            run, FakturowniaInvoice, ResourceType.INVOICE, item,
            {
                "number": p.to_str(item.get("number"), 100),
                "kind": kind,
                "invoice_status": status,
                "income": p.to_bool(item.get("income")) if "income" in item else True,
                "issue_date": p.to_date(item.get("issue_date")),
                "sell_date": p.to_date(item.get("sell_date")),
                "client_fakturownia_id": p.to_int(item.get("client_id")),
                "buyer_name": p.to_str(item.get("buyer_name"), 500),
                "buyer_tax_no": p.to_str(item.get("buyer_tax_no"), 50),
                "seller_name": p.to_str(item.get("seller_name"), 500),
                "department_fakturownia_id": p.to_int(item.get("department_id")),
                "warehouse_fakturownia_id": p.to_int(item.get("warehouse_id")),
                "currency": p.to_str(item.get("currency"), 10),
                "total_net": p.to_decimal(item.get("price_net")),
                "total_gross": p.to_decimal(item.get("price_gross")),
                "paid_amount": p.to_decimal(item.get("paid")),
                "is_correction": kind == "correction",
                "corrected_invoice_fakturownia_id": p.to_int(
                    item.get("from_invoice_id") or item.get("invoice_id")
                ),
                "is_cancelled": is_cancelled,
                "source_updated_at": p.to_datetime(item.get("updated_at")),
            },
            counters, seen,
        )
        if invoice is None:
            return
        positions = item.get("positions") or []
        if positions:
            self._sync_invoice_positions(invoice, positions)

    def _sync_invoice_positions(
        self, invoice: FakturowniaInvoice, positions: list[dict[str, Any]]
    ) -> None:
        self.db.flush()  # make sure invoice.id is assigned
        existing = {
            pos.fakturownia_id: pos
            for pos in self.db.execute(
                select(FakturowniaInvoicePosition).where(
                    FakturowniaInvoicePosition.invoice_id == invoice.id
                )
            ).scalars()
            if pos.fakturownia_id is not None
        }
        seen_position_ids: set[int] = set()
        for item in positions:
            position_fid = p.to_int(item.get("id"))
            row = existing.get(position_fid) if position_fid is not None else None
            if row is None:
                row = FakturowniaInvoicePosition(
                    fakturownia_id=position_fid, invoice_id=invoice.id
                )
                self.db.add(row)
            if position_fid is not None:
                seen_position_ids.add(position_fid)
            row.invoice_fakturownia_id = invoice.fakturownia_id
            row.product_fakturownia_id = p.to_int(item.get("product_id"))
            row.name = p.to_str(item.get("name"), 1000)
            row.description = p.to_str(item.get("description"))
            row.code = p.to_str(item.get("code"), 255)
            row.quantity = p.to_decimal(item.get("quantity"))
            row.quantity_unit = p.to_str(item.get("quantity_unit"), 50)
            row.price_net = p.to_decimal(item.get("price_net"))
            row.price_gross = p.to_decimal(item.get("price_gross"))
            row.total_price_net = p.to_decimal(item.get("total_price_net"))
            row.total_price_gross = p.to_decimal(item.get("total_price_gross"))
            row.tax = p.to_str(item.get("tax"), 20)
            row.raw = item
        # Positions removed upstream disappear from the payload: drop the
        # local mirror rows for this invoice (invoice-level snapshot keeps history).
        for position_fid, row in existing.items():
            if position_fid not in seen_position_ids:
                self.db.delete(row)

    def _sync_warehouse_documents(self, run: SyncRun, full: bool) -> ResourceCounters:
        counters = ResourceCounters()
        seen: set[int] = set()
        for page in self.client.iter_warehouse_documents():
            for item in page:
                self._upsert(
                    run, WarehouseDocument, ResourceType.WAREHOUSE_DOCUMENT, item,
                    {
                        "kind": p.to_str(item.get("kind"), 20),
                        "number": p.to_str(item.get("number"), 100),
                        "warehouse_fakturownia_id": p.to_int(item.get("warehouse_id")),
                        "issue_date": p.to_date(item.get("issue_date")),
                        "client_fakturownia_id": p.to_int(item.get("client_id")),
                        "invoice_fakturownia_id": p.to_int(item.get("invoice_id")),
                        "description": p.to_str(item.get("description")),
                    },
                    counters, seen,
                )
            self.db.flush()
        if full:
            self._mark_deleted(WarehouseDocument, seen, counters)
        return counters

    def _sync_warehouse_actions(self, run: SyncRun, full: bool) -> ResourceCounters:
        counters = ResourceCounters()
        seen: set[int] = set()
        for page in self.client.iter_warehouse_actions():
            for item in page:
                self._upsert(
                    run, WarehouseAction, ResourceType.WAREHOUSE_ACTION, item,
                    {
                        "warehouse_document_fakturownia_id": p.to_int(
                            item.get("warehouse_document_id")
                        ),
                        "warehouse_fakturownia_id": p.to_int(item.get("warehouse_id")),
                        "product_fakturownia_id": p.to_int(item.get("product_id")),
                        "kind": p.to_str(item.get("kind"), 20),
                        "quantity": p.to_decimal(item.get("quantity")),
                        "price_net": p.to_decimal(item.get("price_net")),
                        "occurred_at": p.to_datetime(
                            item.get("created_at") or item.get("issue_date")
                        ),
                    },
                    counters, seen,
                )
            self.db.flush()
        if full:
            self._mark_deleted(WarehouseAction, seen, counters)
        return counters

    def _sync_payments(self, run: SyncRun, full: bool) -> ResourceCounters:
        counters = ResourceCounters()
        seen: set[int] = set()
        for page in self.client.iter_payments():
            for item in page:
                invoice_ids = item.get("invoice_ids") or []
                if item.get("invoice_id"):
                    invoice_ids = list({*invoice_ids, item["invoice_id"]})
                self._upsert(
                    run, FakturowniaPayment, ResourceType.PAYMENT, item,
                    {
                        "name": p.to_str(item.get("name"), 500),
                        "price": p.to_decimal(item.get("price")),
                        "currency": p.to_str(item.get("currency"), 10),
                        "paid_date": p.to_date(item.get("paid_date")),
                        "invoice_fakturownia_ids": invoice_ids,
                    },
                    counters, seen,
                )
            self.db.flush()
        if full:
            self._mark_deleted(FakturowniaPayment, seen, counters)
        return counters

    def _sync_price_lists(self, run: SyncRun, full: bool) -> ResourceCounters:
        counters = ResourceCounters()
        seen: set[int] = set()
        for item in self.client.get_price_lists():
            self._upsert(
                run, FakturowniaPriceList, ResourceType.PRICE_LIST, item,
                {
                    "name": p.to_str(item.get("name"), 255),
                    "currency": p.to_str(item.get("currency"), 10),
                },
                counters, seen,
            )
        if full:
            self._mark_deleted(FakturowniaPriceList, seen, counters)
        return counters

    # ------------------------------------------------------------------ #
    # Watermark handling for incremental sync
    # ------------------------------------------------------------------ #
    def _incremental_date_from(self) -> date:
        setting = self.db.execute(
            select(AppSetting).where(AppSetting.key == LAST_SYNC_SETTING_KEY)
        ).scalar_one_or_none()
        if setting and setting.value:
            last = p.to_datetime(setting.value)
            if last:
                return (last - timedelta(days=INCREMENTAL_OVERLAP_DAYS)).date()
        return date(2000, 1, 1)

    def _store_last_sync_timestamp(self, finished: datetime) -> None:
        setting = self.db.execute(
            select(AppSetting).where(AppSetting.key == LAST_SYNC_SETTING_KEY)
        ).scalar_one_or_none()
        if setting is None:
            setting = AppSetting(
                key=LAST_SYNC_SETTING_KEY,
                description="Timestamp of the last fully successful synchronization",
            )
            self.db.add(setting)
        setting.value = finished.isoformat()
