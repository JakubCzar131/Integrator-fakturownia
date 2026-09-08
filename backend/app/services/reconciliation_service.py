"""Document reconciliation engine ("Tabela Rozliczeniowa").

For every product × warehouse it confronts three independent sources:

* **Fakturownia stock** — what the source system reports,
* **goods receipts** — quantities documented as PZ (external receipt) and
  PW (internal receipt),
* **outbound sales** — quantities on sales invoices and corrections.

    computed = opening balance + ΣPZ + ΣPW − Σsales − Σcorrections

Correction quantities are deltas exactly as Fakturownia reports them (a return
of two pieces arrives as ``-2``), so subtracting them puts stock back — the
same convention the ledger uses.

WZ/RW/MM documents are counted into ``outbound_documents`` for information
only: in a typical Fakturownia setup a WZ accompanies the sales invoice, so
adding both would settle the same goods twice.  Set
``reconciliation_include_outbound_documents`` if the account issues warehouse
documents *instead of* invoice-driven settlement.

Performance contract: the whole snapshot is produced by a handful of grouped
SQL queries against the local mirror.  No external API call happens here — the
sync already fetched everything.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.enums import ReconciliationStatus, WarehouseDocumentKind
from app.models.fakturownia import (
    FakturowniaInvoice,
    FakturowniaInvoicePosition,
    FakturowniaProduct,
    FakturowniaProductStock,
    Warehouse,
    WarehouseDocument,
    WarehouseDocumentPosition,
)
from app.models.product import Product
from app.models.reconciliation import ReconciliationRun, StockReconciliationLine
from app.models.stock import LocalStockBalance, OpeningBalance
from app.services.stock_service import (
    DEFAULT_EXCLUDED_STATUSES,
    DEFAULT_SALE_KINDS,
    SETTING_EXCLUDED_STATUSES,
    SETTING_SALE_KINDS,
    get_setting,
)
from app.services.validation_service import SETTING_DISCREPANCY_TOLERANCE

logger = logging.getLogger(__name__)

ZERO = Decimal("0")

SETTING_INCLUDE_OUTBOUND_DOCUMENTS = "reconciliation_include_outbound_documents"
SETTING_KEEP_RUNS = "reconciliation_keep_runs"
DEFAULT_KEEP_RUNS = 30

Key = tuple[int, int | None]


class ReconciliationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #
    def refresh(
        self,
        user_id: int | None = None,
        trigger: str = "MANUAL",
        sync_run_id: int | None = None,
    ) -> ReconciliationRun:
        started = datetime.now(timezone.utc)
        tolerance = Decimal(
            str(get_setting(self.db, SETTING_DISCREPANCY_TOLERANCE, "0.001"))
        )
        include_outbound = bool(
            get_setting(self.db, SETTING_INCLUDE_OUTBOUND_DOCUMENTS, False)
        )

        run = ReconciliationRun(
            started_at=started,
            triggered_by_user_id=user_id,
            trigger=trigger,
            sync_run_id=sync_run_id,
            tolerance=tolerance,
        )
        self.db.add(run)
        self.db.flush()

        warehouse_by_fid, default_warehouse_id = self._warehouse_lookup()
        receipts = self._document_aggregates(warehouse_by_fid, default_warehouse_id)
        sales = self._invoice_aggregates(warehouse_by_fid, default_warehouse_id)
        openings = self._opening_balances()
        ledger = self._ledger_balances()
        remote, remote_global = self._remote_stock(warehouse_by_fid)
        product_fids = self._product_fakturownia_ids()

        keys: set[Key] = set()
        keys.update(receipts)
        keys.update(sales)
        keys.update(openings)
        keys.update(ledger)
        keys.update(remote)

        discrepancies = 0
        for product_id, warehouse_id in sorted(keys, key=lambda k: (k[0], k[1] or 0)):
            receipt = receipts.get((product_id, warehouse_id), {})
            sale = sales.get((product_id, warehouse_id), {})
            inbound_pz = receipt.get(str(WarehouseDocumentKind.PZ), ZERO)
            inbound_pw = receipt.get(str(WarehouseDocumentKind.PW), ZERO)
            outbound_documents = receipt.get("OUTBOUND", ZERO)
            sold = sale.get("SALE", ZERO)
            corrections = sale.get("CORRECTION", ZERO)
            opening = openings.get((product_id, warehouse_id))
            local_stock = ledger.get((product_id, warehouse_id))

            computed = (opening or ZERO) + inbound_pz + inbound_pw - sold - corrections
            if include_outbound:
                computed -= outbound_documents

            fakturownia_stock = remote.get((product_id, warehouse_id))
            if fakturownia_stock is None:
                product_fid = product_fids.get(product_id)
                fakturownia_stock = (
                    remote_global.get(product_fid) if product_fid is not None else None
                )

            if fakturownia_stock is None:
                difference = None
                status = ReconciliationStatus.NO_REMOTE_STOCK
            else:
                difference = computed - fakturownia_stock
                status = (
                    ReconciliationStatus.OK
                    if abs(difference) <= tolerance
                    else ReconciliationStatus.DISCREPANCY
                )
            if status == ReconciliationStatus.DISCREPANCY:
                discrepancies += 1

            self.db.add(
                StockReconciliationLine(
                    run_id=run.id,
                    product_id=product_id,
                    warehouse_id=warehouse_id,
                    fakturownia_stock=fakturownia_stock,
                    inbound_pz=inbound_pz,
                    inbound_pw=inbound_pw,
                    outbound_documents=outbound_documents,
                    sold_invoices=sold,
                    corrections=corrections,
                    opening_balance=opening,
                    local_ledger_stock=local_stock,
                    computed_stock=computed,
                    difference=difference,
                    status=str(status),
                )
            )

        finished = datetime.now(timezone.utc)
        run.finished_at = finished
        run.duration_seconds = (finished - started).total_seconds()
        run.line_count = len(keys)
        run.discrepancy_count = discrepancies
        run.stats = {
            "products": len({key[0] for key in keys}),
            "warehouses": len({key[1] for key in keys}),
            "include_outbound_documents": include_outbound,
            "tolerance": str(tolerance),
        }
        self.db.flush()
        self._prune_old_runs()
        return run

    def latest_run(self) -> ReconciliationRun | None:
        return self.db.execute(
            select(ReconciliationRun)
            .where(ReconciliationRun.finished_at.isnot(None))
            .order_by(ReconciliationRun.id.desc())
            .limit(1)
        ).scalars().first()

    # ------------------------------------------------------------------ #
    # Aggregates (one grouped query each)
    # ------------------------------------------------------------------ #
    def _warehouse_lookup(self) -> tuple[dict[int, int], int | None]:
        warehouses = self.db.execute(select(Warehouse)).scalars().all()
        mapping = {w.fakturownia_id: w.id for w in warehouses if w.fakturownia_id is not None}
        default = next((w.id for w in warehouses if w.is_default), None)
        if default is None and warehouses:
            default = warehouses[0].id
        return mapping, default

    def _document_aggregates(
        self, warehouse_by_fid: dict[int, int], default_warehouse_id: int | None
    ) -> dict[Key, dict[str, Decimal]]:
        rows = self.db.execute(
            select(
                WarehouseDocumentPosition.mapped_product_id,
                WarehouseDocumentPosition.warehouse_fakturownia_id,
                WarehouseDocumentPosition.document_kind,
                func.sum(WarehouseDocumentPosition.quantity),
            )
            .join(
                WarehouseDocument,
                WarehouseDocument.id == WarehouseDocumentPosition.document_id,
            )
            .where(
                WarehouseDocumentPosition.mapped_product_id.isnot(None),
                WarehouseDocument.is_deleted_upstream.is_(False),
            )
            .group_by(
                WarehouseDocumentPosition.mapped_product_id,
                WarehouseDocumentPosition.warehouse_fakturownia_id,
                WarehouseDocumentPosition.document_kind,
            )
        ).all()

        outbound_kinds = {
            str(WarehouseDocumentKind.WZ),
            str(WarehouseDocumentKind.RW),
            str(WarehouseDocumentKind.MM),
        }
        result: dict[Key, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
        for product_id, warehouse_fid, kind, total in rows:
            key = (product_id, warehouse_by_fid.get(warehouse_fid, default_warehouse_id))
            quantity = Decimal(str(total or 0))
            bucket = "OUTBOUND" if kind in outbound_kinds else (kind or "OTHER")
            result[key][bucket] += abs(quantity) if bucket == "OUTBOUND" else quantity
        return result

    def _invoice_aggregates(
        self, warehouse_by_fid: dict[int, int], default_warehouse_id: int | None
    ) -> dict[Key, dict[str, Decimal]]:
        sale_kinds = list(get_setting(self.db, SETTING_SALE_KINDS, DEFAULT_SALE_KINDS))
        excluded = list(
            get_setting(self.db, SETTING_EXCLUDED_STATUSES, DEFAULT_EXCLUDED_STATUSES)
        )
        rows = self.db.execute(
            select(
                FakturowniaInvoicePosition.mapped_product_id,
                FakturowniaInvoice.warehouse_fakturownia_id,
                FakturowniaInvoice.is_correction,
                func.sum(FakturowniaInvoicePosition.quantity),
            )
            .join(
                FakturowniaInvoice,
                FakturowniaInvoice.id == FakturowniaInvoicePosition.invoice_id,
            )
            .where(
                FakturowniaInvoicePosition.mapped_product_id.isnot(None),
                FakturowniaInvoice.is_cancelled.is_(False),
                FakturowniaInvoice.is_deleted_upstream.is_(False),
                FakturowniaInvoice.income.isnot(False),
                FakturowniaInvoice.invoice_status.notin_(excluded),
                (
                    FakturowniaInvoice.kind.in_(sale_kinds)
                    | FakturowniaInvoice.is_correction.is_(True)
                ),
            )
            .group_by(
                FakturowniaInvoicePosition.mapped_product_id,
                FakturowniaInvoice.warehouse_fakturownia_id,
                FakturowniaInvoice.is_correction,
            )
        ).all()

        result: dict[Key, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
        for product_id, warehouse_fid, is_correction, total in rows:
            key = (product_id, warehouse_by_fid.get(warehouse_fid, default_warehouse_id))
            bucket = "CORRECTION" if is_correction else "SALE"
            result[key][bucket] += Decimal(str(total or 0))
        return result

    def _opening_balances(self) -> dict[Key, Decimal]:
        rows = self.db.execute(
            select(
                OpeningBalance.product_id,
                OpeningBalance.warehouse_id,
                func.sum(OpeningBalance.quantity),
            ).group_by(OpeningBalance.product_id, OpeningBalance.warehouse_id)
        ).all()
        return {
            (product_id, warehouse_id): Decimal(str(total or 0))
            for product_id, warehouse_id, total in rows
        }

    def _ledger_balances(self) -> dict[Key, Decimal]:
        rows = self.db.execute(
            select(
                LocalStockBalance.product_id,
                LocalStockBalance.warehouse_id,
                LocalStockBalance.quantity,
            )
        ).all()
        return {
            (product_id, warehouse_id): Decimal(str(quantity or 0))
            for product_id, warehouse_id, quantity in rows
        }

    def _remote_stock(
        self, warehouse_by_fid: dict[int, int]
    ) -> tuple[dict[Key, Decimal], dict[int, Decimal]]:
        product_by_fid = {
            fid: pid
            for fid, pid in self.db.execute(
                select(Product.fakturownia_product_id, Product.id).where(
                    Product.fakturownia_product_id.isnot(None)
                )
            ).all()
        }
        per_warehouse: dict[Key, Decimal] = {}
        for row in self.db.execute(select(FakturowniaProductStock)).scalars():
            product_id = product_by_fid.get(row.product_fakturownia_id)
            warehouse_id = warehouse_by_fid.get(row.warehouse_fakturownia_id)
            if product_id is None or row.quantity is None:
                continue
            per_warehouse[(product_id, warehouse_id)] = Decimal(str(row.quantity))

        global_stock = {
            fp.fakturownia_id: Decimal(str(fp.quantity))
            for fp in self.db.execute(select(FakturowniaProduct)).scalars()
            if fp.quantity is not None
        }
        return per_warehouse, global_stock

    def _product_fakturownia_ids(self) -> dict[int, int]:
        return {
            pid: fid
            for fid, pid in self.db.execute(
                select(Product.fakturownia_product_id, Product.id).where(
                    Product.fakturownia_product_id.isnot(None)
                )
            ).all()
        }

    # ------------------------------------------------------------------ #
    # Retention
    # ------------------------------------------------------------------ #
    def _prune_old_runs(self) -> None:
        """Keep the trend history bounded (lines are the bulky part)."""
        keep = int(get_setting(self.db, SETTING_KEEP_RUNS, DEFAULT_KEEP_RUNS) or DEFAULT_KEEP_RUNS)
        ids = [
            row[0]
            for row in self.db.execute(
                select(ReconciliationRun.id).order_by(ReconciliationRun.id.desc())
            ).all()
        ]
        stale = ids[keep:]
        if stale:
            self.db.execute(
                delete(ReconciliationRun).where(ReconciliationRun.id.in_(stale))
            )


def reconciled_stock_map(db: Session) -> dict[int, Decimal]:
    """Computed stock per product from the latest snapshot (summed over warehouses)."""
    service = ReconciliationService(db)
    run = service.latest_run()
    if run is None:
        return {}
    rows = db.execute(
        select(
            StockReconciliationLine.product_id,
            func.sum(StockReconciliationLine.computed_stock),
        )
        .where(StockReconciliationLine.run_id == run.id)
        .group_by(StockReconciliationLine.product_id)
    ).all()
    return {product_id: Decimal(str(total or 0)) for product_id, total in rows}


def reconciliation_summary(db: Session) -> dict[str, Any]:
    run = ReconciliationService(db).latest_run()
    if run is None:
        return {"run": None, "line_count": 0, "discrepancy_count": 0}
    return {
        "run_id": run.id,
        "computed_at": run.finished_at,
        "line_count": run.line_count,
        "discrepancy_count": run.discrepancy_count,
        "trigger": run.trigger,
    }
