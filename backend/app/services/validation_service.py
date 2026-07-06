"""Sales validation engine.

Runs all business checks (product recognition, quantities, units, stock
sufficiency, negative stock, duplicates, cancellations, corrections, opening
balances, upstream stock discrepancies…) and materializes findings as
``validation_issues``.

Issue lifecycle:

* Each finding has a stable ``dedupe_key`` so re-running validation *updates*
  the existing issue instead of duplicating it.
* Issues no longer detected are auto-RESOLVED.
* Issues manually IGNORED by an operator stay ignored.
* RESOLVED issues that reappear are reopened.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import (
    IssueSeverity,
    ProductKind,
    StockMovementType,
    ValidationIssueType,
    ValidationRunStatus,
    ValidationStatus,
)
from app.models.fakturownia import (
    FakturowniaInvoice,
    FakturowniaProduct,
    FakturowniaProductStock,
    Warehouse,
)
from app.models.product import Product, ProductBundleComponent
from app.models.stock import LocalStockBalance, LocalStockLedgerEntry, OpeningBalance
from app.models.user import User
from app.models.validation import ValidationIssue, ValidationRun
from app.services.stock_service import (
    DEFAULT_EXCLUDED_STATUSES,
    DEFAULT_SALE_KINDS,
    SETTING_EXCLUDED_STATUSES,
    SETTING_SALE_KINDS,
    StockService,
    get_setting,
)

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
KNOWN_INVOICE_KINDS = {
    "vat", "proforma", "bill", "receipt", "advance", "final", "correction",
    "invoice", "estimate", "payment", "correction_note", "accounting_note",
    "client_order", "dw", "kp", "kw", "vat_margin", "vat_rr", "vat_mp",
}
SETTING_QUANTITY_MAX = "validation_max_reasonable_quantity"
SETTING_DISCREPANCY_TOLERANCE = "validation_stock_discrepancy_tolerance"

# issue_type -> (default status, severity, recommended action for the operator)
ISSUE_DEFAULTS: dict[ValidationIssueType, tuple[ValidationStatus, IssueSeverity, str]] = {
    ValidationIssueType.PRODUCT_NOT_RECOGNIZED: (
        ValidationStatus.NEEDS_MAPPING, IssueSeverity.HIGH,
        "Przypisz pozycję do produktu w module Mapowania produktów.",
    ),
    ValidationIssueType.PRODUCT_ID_MISSING: (
        ValidationStatus.WARNING, IssueSeverity.LOW,
        "Pozycja rozpoznana przez alias/mapowanie. Zweryfikuj i zatwierdź mapowanie.",
    ),
    ValidationIssueType.NEGATIVE_STOCK: (
        ValidationStatus.ERROR, IssueSeverity.CRITICAL,
        "Uzupełnij stan początkowy, dodaj lokalną korektę magazynową lub zweryfikuj fakturę.",
    ),
    ValidationIssueType.INSUFFICIENT_STOCK: (
        ValidationStatus.ERROR, IssueSeverity.HIGH,
        "Sprawdź, czy przed tą sprzedażą nie brakuje przyjęcia magazynowego lub stanu początkowego.",
    ),
    ValidationIssueType.UNIT_MISMATCH: (
        ValidationStatus.WARNING, IssueSeverity.MEDIUM,
        "Ujednolić jednostkę miary na pozycji faktury i karcie produktu (alias jednostki).",
    ),
    ValidationIssueType.DUPLICATE_INVOICE: (
        ValidationStatus.WARNING, IssueSeverity.HIGH,
        "Zweryfikuj, czy dokumenty nie zostały wystawione podwójnie.",
    ),
    ValidationIssueType.CANCELLED_INVOICE_INCLUDED: (
        ValidationStatus.ERROR, IssueSeverity.HIGH,
        "Uruchom przeliczenie stanów magazynowych (dokument anulowany nie powinien zdejmować stanu).",
    ),
    ValidationIssueType.CORRECTION_NOT_HANDLED: (
        ValidationStatus.WARNING, IssueSeverity.HIGH,
        "Zweryfikuj ręcznie fakturę korygującą i dokument pierwotny.",
    ),
    ValidationIssueType.SERVICE_INCLUDED_IN_STOCK: (
        ValidationStatus.WARNING, IssueSeverity.MEDIUM,
        "Popraw klasyfikację produktu (usługa nie powinna być kontrolowana magazynowo).",
    ),
    ValidationIssueType.MISSING_OPENING_BALANCE: (
        ValidationStatus.NEEDS_OPENING_BALANCE, IssueSeverity.HIGH,
        "Ustaw lokalny stan początkowy produktu w tym magazynie.",
    ),
    ValidationIssueType.STOCK_DISCREPANCY: (
        ValidationStatus.WARNING, IssueSeverity.MEDIUM,
        "Porównaj lokalny ledger z danymi Fakturowni i dodaj korektę lokalną, jeśli to konieczne.",
    ),
    ValidationIssueType.UNKNOWN_DOCUMENT_TYPE: (
        ValidationStatus.WARNING, IssueSeverity.MEDIUM,
        "Dodaj regułę obsługi tego typu dokumentu w Ustawieniach.",
    ),
    ValidationIssueType.UNKNOWN_PRODUCT_TYPE: (
        ValidationStatus.NEEDS_MAPPING, IssueSeverity.MEDIUM,
        "Sklasyfikuj produkt (towar / usługa / zestaw / ignorowany) na karcie produktu.",
    ),
    ValidationIssueType.INVALID_QUANTITY: (
        ValidationStatus.ERROR, IssueSeverity.HIGH,
        "Zweryfikuj ilość na pozycji faktury w Fakturowni.",
    ),
    ValidationIssueType.MAPPING_CONFLICT: (
        ValidationStatus.NEEDS_MAPPING, IssueSeverity.HIGH,
        "Rozstrzygnij konflikt mapowania — wiele produktów pasuje do tej pozycji.",
    ),
    ValidationIssueType.LOCAL_RULE_REQUIRED: (
        ValidationStatus.WARNING, IssueSeverity.MEDIUM,
        "Zdefiniuj lokalną regułę (np. skład zestawu) dla tego produktu.",
    ),
    ValidationIssueType.SALE_BEFORE_OPENING_BALANCE: (
        ValidationStatus.NEEDS_OPENING_BALANCE, IssueSeverity.MEDIUM,
        "Sprzedaż przed datą stanu początkowego — cofnij datę stanu początkowego lub skoryguj ilość.",
    ),
    ValidationIssueType.INACTIVE_PRODUCT_SOLD: (
        ValidationStatus.WARNING, IssueSeverity.MEDIUM,
        "Produkt nieaktywny/wyłączony pojawia się na fakturze — zweryfikuj kartę produktu.",
    ),
    ValidationIssueType.DOUBLE_STOCK_SETTLEMENT: (
        ValidationStatus.ERROR, IssueSeverity.CRITICAL,
        "Pozycja rozliczona magazynowo więcej niż raz — uruchom przeliczenie stanów i zgłoś błąd.",
    ),
    ValidationIssueType.UNKNOWN_UNIT: (
        ValidationStatus.WARNING, IssueSeverity.LOW,
        "Uzupełnij jednostkę miary na karcie produktu.",
    ),
}


def _dedupe_key(
    issue_type: ValidationIssueType,
    invoice_id: int | None,
    position_id: int | None,
    product_id: int | None,
    warehouse_id: int | None,
) -> str:
    raw = f"{issue_type}|{invoice_id}|{position_id}|{product_id}|{warehouse_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class _IssueCollector:
    def __init__(self) -> None:
        self.findings: dict[str, dict[str, Any]] = {}

    def add(
        self,
        issue_type: ValidationIssueType,
        *,
        invoice_id: int | None = None,
        position_id: int | None = None,
        product_id: int | None = None,
        warehouse_id: int | None = None,
        quantity: Decimal | None = None,
        stock_before: Decimal | None = None,
        stock_after: Decimal | None = None,
        technical: str = "",
        business: str = "",
    ) -> None:
        key = _dedupe_key(issue_type, invoice_id, position_id, product_id, warehouse_id)
        status, severity, action = ISSUE_DEFAULTS[issue_type]
        self.findings[key] = {
            "issue_type": str(issue_type),
            "status": str(status),
            "severity": str(severity),
            "invoice_id": invoice_id,
            "invoice_position_id": position_id,
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "quantity": quantity,
            "stock_before": stock_before,
            "stock_after": stock_after,
            "technical_description": technical,
            "business_description": business,
            "recommended_action": action,
            "dedupe_key": key,
        }


class ValidationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def run_validation(
        self, user: User | None = None, rebuild_stock: bool = True
    ) -> ValidationRun:
        run = ValidationRun(
            status=str(ValidationRunStatus.RUNNING),
            triggered_by_user_id=user.id if user else None,
        )
        self.db.add(run)
        self.db.commit()
        started = datetime.now(timezone.utc)

        try:
            if rebuild_stock:
                StockService(self.db).rebuild_stock()
                self.db.flush()

            collector = _IssueCollector()
            counters = self._collect_findings(collector)
            created, updated, auto_resolved = self._materialize(run, collector)

            finished = datetime.now(timezone.utc)
            run.finished_at = finished
            run.duration_seconds = (finished - started).total_seconds()
            run.invoices_checked = counters["invoices"]
            run.positions_checked = counters["positions"]
            run.issues_created = created
            run.issues_auto_resolved = auto_resolved
            run.stats = {
                **counters,
                "issues_created": created,
                "issues_updated": updated,
                "issues_auto_resolved": auto_resolved,
            }
            run.status = str(ValidationRunStatus.SUCCESS)
            run.message = (
                f"Sprawdzono {counters['invoices']} faktur i {counters['positions']} pozycji; "
                f"nowych problemów: {created}, zamkniętych automatycznie: {auto_resolved}"
            )
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            run.status = str(ValidationRunStatus.FAILED)
            run.finished_at = datetime.now(timezone.utc)
            run.message = f"Walidacja nie powiodła się: {exc}"
            self.db.commit()
            logger.exception("Validation run failed")
            raise
        return run

    # ------------------------------------------------------------------ #
    def _collect_findings(self, c: _IssueCollector) -> dict[str, int]:
        db = self.db
        sale_kinds = set(get_setting(db, SETTING_SALE_KINDS, DEFAULT_SALE_KINDS))
        excluded_statuses = set(
            get_setting(db, SETTING_EXCLUDED_STATUSES, DEFAULT_EXCLUDED_STATUSES)
        )
        max_quantity = Decimal(str(get_setting(db, SETTING_QUANTITY_MAX, 100000)))
        tolerance = Decimal(str(get_setting(db, SETTING_DISCREPANCY_TOLERANCE, "0.001")))

        products: dict[int, Product] = {
            prod.id: prod for prod in db.execute(select(Product)).scalars()
        }
        bundles_with_components = {
            comp.bundle_product_id
            for comp in db.execute(select(ProductBundleComponent)).scalars()
        }
        opening_balances: dict[tuple[int, int], OpeningBalance] = {
            (ob.product_id, ob.warehouse_id): ob
            for ob in db.execute(select(OpeningBalance)).scalars()
        }
        default_wh = StockService(db)._default_warehouse().id
        warehouse_map = {
            w.fakturownia_id: w.id
            for w in db.execute(select(Warehouse)).scalars()
            if w.fakturownia_id is not None
        }

        # Ledger entries indexed by invoice position for stock checks.
        ledger_by_position: dict[int, list[LocalStockLedgerEntry]] = {}
        ledger_by_invoice: dict[int, int] = {}
        for entry in db.execute(select(LocalStockLedgerEntry)).scalars():
            if entry.source_invoice_position_id is not None:
                ledger_by_position.setdefault(
                    entry.source_invoice_position_id, []
                ).append(entry)
            if entry.source_invoice_id is not None:
                ledger_by_invoice[entry.source_invoice_id] = (
                    ledger_by_invoice.get(entry.source_invoice_id, 0) + 1
                )

        invoices = db.execute(
            select(FakturowniaInvoice)
            .options(selectinload(FakturowniaInvoice.positions))
            .where(FakturowniaInvoice.is_deleted_upstream.is_(False))
        ).scalars().all()
        invoices_by_fid = {inv.fakturownia_id: inv for inv in invoices}

        # ---- invoice-level: duplicates -------------------------------- #
        groups: dict[tuple[str, int | None], list[FakturowniaInvoice]] = {}
        for inv in invoices:
            if inv.is_cancelled or not inv.number:
                continue
            groups.setdefault((inv.number, inv.client_fakturownia_id), []).append(inv)
        for (number, _client), group in groups.items():
            if len(group) > 1:
                for inv in group[1:]:
                    c.add(
                        ValidationIssueType.DUPLICATE_INVOICE,
                        invoice_id=inv.id,
                        technical=f"invoice number={number} appears {len(group)}x "
                                  f"(fakturownia_ids={[g.fakturownia_id for g in group]})",
                        business=f"Faktura o numerze {number} dla tego samego klienta "
                                 f"występuje {len(group)} razy.",
                    )

        positions_checked = 0
        for invoice in invoices:
            invoice_wh = warehouse_map.get(invoice.warehouse_fakturownia_id, default_wh)

            # cancelled / excluded documents must not settle stock
            if invoice.is_cancelled or invoice.invoice_status in excluded_statuses:
                if ledger_by_invoice.get(invoice.id):
                    c.add(
                        ValidationIssueType.CANCELLED_INVOICE_INCLUDED,
                        invoice_id=invoice.id,
                        technical=f"cancelled/excluded invoice has "
                                  f"{ledger_by_invoice[invoice.id]} ledger entries",
                        business=f"Anulowana/wykluczona faktura {invoice.number} "
                                 "została rozliczona magazynowo.",
                    )
                continue

            if invoice.kind and invoice.kind not in KNOWN_INVOICE_KINDS:
                c.add(
                    ValidationIssueType.UNKNOWN_DOCUMENT_TYPE,
                    invoice_id=invoice.id,
                    technical=f"kind={invoice.kind}",
                    business=f"Nieznany typ dokumentu „{invoice.kind}” — "
                             "wymaga reguły lokalnej.",
                )

            if invoice.is_correction:
                original = invoices_by_fid.get(invoice.corrected_invoice_fakturownia_id)
                if invoice.corrected_invoice_fakturownia_id is None or original is None:
                    c.add(
                        ValidationIssueType.CORRECTION_NOT_HANDLED,
                        invoice_id=invoice.id,
                        technical=f"correction without resolvable original "
                                  f"(from_invoice_id="
                                  f"{invoice.corrected_invoice_fakturownia_id})",
                        business=f"Korekta {invoice.number} nie ma powiązanego "
                                 "dokumentu pierwotnego w danych lokalnych.",
                    )

            is_sale_like = invoice.kind in sale_kinds or invoice.is_correction
            if not is_sale_like:
                continue

            for position in invoice.positions:
                positions_checked += 1
                self._check_position(
                    c, invoice, position, products, bundles_with_components,
                    opening_balances, ledger_by_position, invoice_wh, max_quantity,
                )

        # ---- product/warehouse-level checks --------------------------- #
        self._check_opening_balances_and_discrepancies(
            c, products, opening_balances, tolerance
        )

        return {"invoices": len(invoices), "positions": positions_checked}

    # ------------------------------------------------------------------ #
    def _check_position(
        self,
        c: _IssueCollector,
        invoice: FakturowniaInvoice,
        position,
        products: dict[int, Product],
        bundles_with_components: set[int],
        opening_balances: dict[tuple[int, int], OpeningBalance],
        ledger_by_position: dict[int, list[LocalStockLedgerEntry]],
        invoice_wh: int,
        max_quantity: Decimal,
    ) -> None:
        quantity = position.quantity

        # 1/2/13: product recognition
        if position.mapped_product_id is None:
            if position.mapping_status == "REJECTED":
                c.add(
                    ValidationIssueType.MAPPING_CONFLICT,
                    invoice_id=invoice.id, position_id=position.id,
                    quantity=quantity,
                    technical=f"ambiguous mapping for name={position.name!r} "
                              f"code={position.code!r}",
                    business=f"Pozycja „{position.name}” pasuje do wielu produktów — "
                             "wymaga ręcznego rozstrzygnięcia.",
                )
            else:
                c.add(
                    ValidationIssueType.PRODUCT_NOT_RECOGNIZED,
                    invoice_id=invoice.id, position_id=position.id,
                    quantity=quantity,
                    technical=f"no product_id and no mapping "
                              f"(name={position.name!r}, code={position.code!r})",
                    business=f"Pozycja „{position.name}” z faktury {invoice.number} "
                             "nie została rozpoznana jako produkt.",
                )
            return

        product = products.get(position.mapped_product_id)
        if product is None:
            return

        if position.product_fakturownia_id is None:
            c.add(
                ValidationIssueType.PRODUCT_ID_MISSING,
                invoice_id=invoice.id, position_id=position.id,
                product_id=product.id, quantity=quantity,
                technical=f"resolved via {position.mapping_match_type} "
                          f"(status={position.mapping_status})",
                business=f"Pozycja „{position.name}” nie ma product_id w Fakturowni — "
                         "rozpoznana lokalnie przez mapowanie.",
            )

        # 3/4: product type
        if product.kind == str(ProductKind.NEEDS_MAPPING):
            c.add(
                ValidationIssueType.UNKNOWN_PRODUCT_TYPE,
                invoice_id=invoice.id, position_id=position.id,
                product_id=product.id, quantity=quantity,
                technical=f"product.kind={product.kind}",
                business=f"Produkt „{product.name}” nie ma ustalonej klasyfikacji "
                         "(towar/usługa/zestaw).",
            )
        if product.kind == str(ProductKind.SERVICE) and product.is_stock_controlled:
            c.add(
                ValidationIssueType.SERVICE_INCLUDED_IN_STOCK,
                invoice_id=invoice.id, position_id=position.id,
                product_id=product.id, quantity=quantity,
                technical="service product flagged as stock-controlled",
                business=f"Usługa „{product.name}” jest oznaczona jako kontrolowana "
                         "magazynowo.",
            )
        if product.kind == str(ProductKind.BUNDLE) and product.id not in bundles_with_components:
            c.add(
                ValidationIssueType.LOCAL_RULE_REQUIRED,
                invoice_id=invoice.id, position_id=position.id,
                product_id=product.id, quantity=quantity,
                technical="bundle product without local composition",
                business=f"Zestaw „{product.name}” nie ma zdefiniowanego składu — "
                         "sprzedaż nie rozlicza magazynu.",
            )

        # 14: inactive product
        if not product.is_active:
            c.add(
                ValidationIssueType.INACTIVE_PRODUCT_SOLD,
                invoice_id=invoice.id, position_id=position.id,
                product_id=product.id, quantity=quantity,
                technical="product.is_active=False",
                business=f"Nieaktywny produkt „{product.name}” występuje na fakturze "
                         f"{invoice.number}.",
            )

        # 5: quantity sanity (corrections may legitimately be negative)
        if quantity is None or (quantity <= ZERO and not invoice.is_correction):
            c.add(
                ValidationIssueType.INVALID_QUANTITY,
                invoice_id=invoice.id, position_id=position.id,
                product_id=product.id, quantity=quantity,
                technical=f"quantity={quantity}",
                business=f"Nieprawidłowa ilość ({quantity}) na pozycji „{position.name}”.",
            )
        elif quantity is not None and abs(quantity) > max_quantity:
            c.add(
                ValidationIssueType.INVALID_QUANTITY,
                invoice_id=invoice.id, position_id=position.id,
                product_id=product.id, quantity=quantity,
                technical=f"quantity={quantity} exceeds threshold {max_quantity}",
                business=f"Podejrzanie duża ilość ({quantity}) na pozycji „{position.name}”.",
            )

        # 6/20: unit of measure
        pos_unit = (position.quantity_unit or "").strip().lower()
        prod_unit = (product.unit or "").strip().lower()
        if not product.is_stock_controlled:
            pass
        elif pos_unit and prod_unit and pos_unit != prod_unit:
            c.add(
                ValidationIssueType.UNIT_MISMATCH,
                invoice_id=invoice.id, position_id=position.id,
                product_id=product.id, quantity=quantity,
                technical=f"position unit={pos_unit!r} vs product unit={prod_unit!r}",
                business=f"Jednostka na fakturze ({position.quantity_unit}) różni się od "
                         f"jednostki produktu ({product.unit}).",
            )
        elif not pos_unit and not prod_unit:
            c.add(
                ValidationIssueType.UNKNOWN_UNIT,
                invoice_id=invoice.id, position_id=position.id,
                product_id=product.id, quantity=quantity,
                technical="no unit on position nor product",
                business=f"Brak jednostki miary dla pozycji „{position.name}”.",
            )

        # 7/8/17: stock checks based on the rebuilt ledger
        entries = ledger_by_position.get(position.id, [])
        sale_entries_per_product: dict[int, int] = {}
        for entry in entries:
            if entry.movement_type == str(StockMovementType.SALE):
                sale_entries_per_product[entry.product_id] = (
                    sale_entries_per_product.get(entry.product_id, 0) + 1
                )
            if entry.quantity_change < ZERO:
                needed = -entry.quantity_change
                if entry.balance_before < needed:
                    c.add(
                        ValidationIssueType.INSUFFICIENT_STOCK,
                        invoice_id=invoice.id, position_id=position.id,
                        product_id=entry.product_id, warehouse_id=entry.warehouse_id,
                        quantity=quantity,
                        stock_before=entry.balance_before,
                        stock_after=entry.balance_after,
                        technical=f"needed={needed}, balance_before={entry.balance_before}",
                        business=f"W dniu sprzedaży brakowało stanu magazynowego dla "
                                 f"„{product.name}” (potrzeba {needed}, było "
                                 f"{entry.balance_before}).",
                    )
                if entry.balance_after < ZERO:
                    c.add(
                        ValidationIssueType.NEGATIVE_STOCK,
                        invoice_id=invoice.id, position_id=position.id,
                        product_id=entry.product_id, warehouse_id=entry.warehouse_id,
                        quantity=quantity,
                        stock_before=entry.balance_before,
                        stock_after=entry.balance_after,
                        technical=f"balance_after={entry.balance_after}",
                        business=f"Sprzedaż z faktury {invoice.number} powoduje stan "
                                 f"ujemny produktu „{product.name}” "
                                 f"({entry.balance_after}).",
                    )
        for product_id, count in sale_entries_per_product.items():
            if count > 1:
                c.add(
                    ValidationIssueType.DOUBLE_STOCK_SETTLEMENT,
                    invoice_id=invoice.id, position_id=position.id,
                    product_id=product_id,
                    quantity=quantity,
                    technical=f"{count} SALE ledger entries for one position/product",
                    business="Pozycja została rozliczona magazynowo więcej niż raz.",
                )

        # 19: sale before opening balance date
        if product.is_stock_controlled and entries:
            for entry in entries:
                ob = opening_balances.get((entry.product_id, entry.warehouse_id))
                if ob is not None and entry.occurred_at.date() < ob.as_of_date:
                    c.add(
                        ValidationIssueType.SALE_BEFORE_OPENING_BALANCE,
                        invoice_id=invoice.id, position_id=position.id,
                        product_id=entry.product_id, warehouse_id=entry.warehouse_id,
                        quantity=quantity,
                        technical=f"sale at {entry.occurred_at.date()} < opening balance "
                                  f"date {ob.as_of_date}",
                        business=f"Sprzedaż „{product.name}” przed datą stanu "
                                 f"początkowego ({ob.as_of_date}).",
                    )

    # ------------------------------------------------------------------ #
    def _check_opening_balances_and_discrepancies(
        self,
        c: _IssueCollector,
        products: dict[int, Product],
        opening_balances: dict[tuple[int, int], OpeningBalance],
        tolerance: Decimal,
    ) -> None:
        db = self.db
        balances = db.execute(select(LocalStockBalance)).scalars().all()
        warehouses = {w.id: w for w in db.execute(select(Warehouse)).scalars()}
        remote_stock: dict[tuple[int, int], Decimal] = {}
        for row in db.execute(select(FakturowniaProductStock)).scalars():
            if row.quantity is not None:
                remote_stock[
                    (row.product_fakturownia_id, row.warehouse_fakturownia_id)
                ] = row.quantity
        remote_global: dict[int, Decimal] = {
            fp.fakturownia_id: fp.quantity
            for fp in db.execute(select(FakturowniaProduct)).scalars()
            if fp.quantity is not None
        }

        # 18: sales without any opening balance for the product+warehouse
        for balance in balances:
            product = products.get(balance.product_id)
            if product is None or not product.is_stock_controlled:
                continue
            has_ob = (balance.product_id, balance.warehouse_id) in opening_balances
            if not has_ob and balance.last_sale_at is not None:
                warehouse = warehouses.get(balance.warehouse_id)
                c.add(
                    ValidationIssueType.MISSING_OPENING_BALANCE,
                    product_id=balance.product_id,
                    warehouse_id=balance.warehouse_id,
                    stock_after=balance.quantity,
                    technical="sales exist but no opening balance record",
                    business=f"Produkt „{product.name}” ma sprzedaż w magazynie "
                             f"„{warehouse.name if warehouse else balance.warehouse_id}”, "
                             "ale nie ustawiono stanu początkowego.",
                )

        # 15: discrepancy between local balance and stock reported by Fakturownia
        for balance in balances:
            product = products.get(balance.product_id)
            if product is None or not product.is_stock_controlled:
                continue
            if product.fakturownia_product_id is None:
                continue
            warehouse = warehouses.get(balance.warehouse_id)
            remote_qty = None
            if warehouse is not None and warehouse.fakturownia_id is not None:
                remote_qty = remote_stock.get(
                    (product.fakturownia_product_id, warehouse.fakturownia_id)
                )
            if remote_qty is None:
                remote_qty = remote_global.get(product.fakturownia_product_id)
            if remote_qty is None:
                continue
            difference = balance.quantity - remote_qty
            if abs(difference) > tolerance:
                c.add(
                    ValidationIssueType.STOCK_DISCREPANCY,
                    product_id=balance.product_id,
                    warehouse_id=balance.warehouse_id,
                    stock_before=remote_qty,
                    stock_after=balance.quantity,
                    quantity=difference,
                    technical=f"local={balance.quantity}, fakturownia={remote_qty}, "
                              f"diff={difference}",
                    business=f"Stan lokalny produktu „{product.name}” "
                             f"({balance.quantity}) różni się od stanu w Fakturowni "
                             f"({remote_qty}) o {difference}.",
                )

    # ------------------------------------------------------------------ #
    def _materialize(
        self, run: ValidationRun, c: _IssueCollector
    ) -> tuple[int, int, int]:
        db = self.db
        existing: dict[str, ValidationIssue] = {
            issue.dedupe_key: issue
            for issue in db.execute(select(ValidationIssue)).scalars()
        }
        created = updated = 0
        now = datetime.now(timezone.utc)

        for key, data in c.findings.items():
            issue = existing.get(key)
            if issue is None:
                issue = ValidationIssue(validation_run_id=run.id, **data)
                db.add(issue)
                created += 1
                continue
            if issue.status == str(ValidationStatus.IGNORED):
                continue  # operator decision wins
            if issue.status == str(ValidationStatus.RESOLVED):
                issue.status = data["status"]  # reappeared -> reopen
                issue.resolved_at = None
                issue.resolved_by_user_id = None
            issue.validation_run_id = run.id
            for field in (
                "severity", "quantity", "stock_before", "stock_after",
                "technical_description", "business_description", "recommended_action",
            ):
                setattr(issue, field, data[field])
            updated += 1

        auto_resolved = 0
        open_statuses = {
            str(ValidationStatus.WARNING), str(ValidationStatus.ERROR),
            str(ValidationStatus.NEEDS_MAPPING),
            str(ValidationStatus.NEEDS_OPENING_BALANCE),
        }
        for key, issue in existing.items():
            if key not in c.findings and issue.status in open_statuses:
                issue.status = str(ValidationStatus.RESOLVED)
                issue.resolved_at = now
                auto_resolved += 1

        db.flush()
        return created, updated, auto_resolved
