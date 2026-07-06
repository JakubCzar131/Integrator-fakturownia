"""Local warehouse engine.

The ledger (``local_stock_ledger``) is a *derived projection* rebuilt
deterministically from source records:

* ``opening_balances``           → OPENING_BALANCE movements,
* sales invoices (mirrored)      → SALE movements (stock-controlled products),
* correction invoices            → SALE_CORRECTION movements,
* ``local_stock_adjustments``    → MANUAL_ADJUSTMENT movements,
* imported Fakturownia warehouse actions (optional, off by default to avoid
  double counting with invoices) → IMPORTED_WAREHOUSE_ACTION movements.

Because the ledger is derived, ``rebuild_stock`` can always recompute
balances from scratch; history of *source* records is never deleted —
mistakes are corrected with reversal adjustments.

Business assumptions implemented here are documented in docs/ASSUMPTIONS.md.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.enums import ProductKind, StockMovementType
from app.models.fakturownia import (
    FakturowniaInvoice,
    FakturowniaInvoicePosition,
    Warehouse,
    WarehouseAction,
)
from app.models.product import Product, ProductBundleComponent
from app.models.settings import AppSetting
from app.models.stock import (
    LocalStockAdjustment,
    LocalStockBalance,
    LocalStockLedgerEntry,
    OpeningBalance,
)

logger = logging.getLogger(__name__)

ZERO = Decimal("0")

# Invoice kinds that settle stock as a sale (see ASSUMPTIONS.md).
DEFAULT_SALE_KINDS = ["vat", "receipt", "bill", "final", "invoice"]
# Invoice statuses excluded from stock settlement and validation.
DEFAULT_EXCLUDED_STATUSES = ["rejected"]

SETTING_SALE_KINDS = "stock_sale_invoice_kinds"
SETTING_EXCLUDED_STATUSES = "stock_excluded_invoice_statuses"
SETTING_USE_WAREHOUSE_ACTIONS = "stock_use_imported_warehouse_actions"


def get_setting(db: Session, key: str, default: Any) -> Any:
    row = db.execute(select(AppSetting).where(AppSetting.key == key)).scalar_one_or_none()
    if row is None or row.value is None:
        return default
    return row.value


@dataclass
class _PendingMovement:
    product_id: int
    warehouse_id: int
    movement_type: StockMovementType
    quantity_change: Decimal
    occurred_at: datetime
    source_invoice_id: int | None = None
    source_invoice_position_id: int | None = None
    source_adjustment_id: int | None = None
    source_opening_balance_id: int | None = None
    source_warehouse_action_id: int | None = None
    description: str | None = None
    created_by_user_id: int | None = None
    # Ordering priority within the same timestamp: inbound before outbound so
    # same-day deliveries are counted before sales.
    priority: int = 5


def _dt(d: date, at: time = time(12, 0)) -> datetime:
    return datetime.combine(d, at, tzinfo=timezone.utc)


def _aware(value: datetime) -> datetime:
    """SQLite (tests) returns naive datetimes; treat them as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class StockService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Rebuild
    # ------------------------------------------------------------------ #
    def rebuild_stock(self, user_id: int | None = None) -> dict[str, Any]:
        """Rebuild the whole ledger and all balances from source records."""
        movements = self._collect_movements()
        movements.sort(key=lambda m: (m.occurred_at, m.priority, m.product_id))

        self.db.execute(delete(LocalStockLedgerEntry))
        self.db.execute(delete(LocalStockBalance))
        self.db.flush()

        balances: dict[tuple[int, int], Decimal] = {}
        last_movement: dict[tuple[int, int], datetime] = {}
        last_sale: dict[tuple[int, int], datetime] = {}
        sequence = 0
        for m in movements:
            key = (m.product_id, m.warehouse_id)
            before = balances.get(key, ZERO)
            after = before + m.quantity_change
            balances[key] = after
            last_movement[key] = m.occurred_at
            if m.movement_type == StockMovementType.SALE:
                last_sale[key] = m.occurred_at
            sequence += 1
            self.db.add(
                LocalStockLedgerEntry(
                    product_id=m.product_id,
                    warehouse_id=m.warehouse_id,
                    movement_type=str(m.movement_type),
                    quantity_change=m.quantity_change,
                    balance_before=before,
                    balance_after=after,
                    occurred_at=m.occurred_at,
                    sequence=sequence,
                    source_invoice_id=m.source_invoice_id,
                    source_invoice_position_id=m.source_invoice_position_id,
                    source_adjustment_id=m.source_adjustment_id,
                    source_opening_balance_id=m.source_opening_balance_id,
                    source_warehouse_action_id=m.source_warehouse_action_id,
                    description=m.description,
                    created_by_user_id=m.created_by_user_id,
                )
            )

        now = datetime.now(timezone.utc)
        for (product_id, warehouse_id), quantity in balances.items():
            self.db.add(
                LocalStockBalance(
                    product_id=product_id,
                    warehouse_id=warehouse_id,
                    quantity=quantity,
                    last_movement_at=last_movement.get((product_id, warehouse_id)),
                    last_sale_at=last_sale.get((product_id, warehouse_id)),
                    recalculated_at=now,
                )
            )
        self.db.flush()
        negative = sum(1 for q in balances.values() if q < ZERO)
        return {
            "movements": sequence,
            "balances": len(balances),
            "negative_balances": negative,
        }

    # ------------------------------------------------------------------ #
    # Movement collection
    # ------------------------------------------------------------------ #
    def _collect_movements(self) -> list[_PendingMovement]:
        movements: list[_PendingMovement] = []
        movements.extend(self._opening_balance_movements())
        movements.extend(self._invoice_movements())
        movements.extend(self._manual_adjustment_movements())
        if get_setting(self.db, SETTING_USE_WAREHOUSE_ACTIONS, False):
            movements.extend(self._imported_warehouse_action_movements())
        return movements

    def _default_warehouse(self) -> Warehouse:
        warehouse = self.db.execute(
            select(Warehouse).where(Warehouse.is_default.is_(True))
        ).scalars().first()
        if warehouse is None:
            warehouse = self.db.execute(select(Warehouse)).scalars().first()
        if warehouse is None:
            warehouse = Warehouse(
                name="Magazyn główny (lokalny)", kind="local", is_default=True
            )
            self.db.add(warehouse)
            self.db.flush()
        return warehouse

    def _warehouse_map(self) -> dict[int, int]:
        return {
            w.fakturownia_id: w.id
            for w in self.db.execute(select(Warehouse)).scalars()
            if w.fakturownia_id is not None
        }

    def _opening_balance_movements(self) -> list[_PendingMovement]:
        result = []
        for ob in self.db.execute(select(OpeningBalance)).scalars():
            result.append(
                _PendingMovement(
                    product_id=ob.product_id,
                    warehouse_id=ob.warehouse_id,
                    movement_type=StockMovementType.OPENING_BALANCE,
                    quantity_change=ob.quantity,
                    occurred_at=_dt(ob.as_of_date, time(0, 0)),
                    source_opening_balance_id=ob.id,
                    description=ob.note or "Stan początkowy",
                    created_by_user_id=ob.created_by_user_id,
                    priority=0,
                )
            )
        return result

    def _invoice_movements(self) -> list[_PendingMovement]:
        sale_kinds = set(get_setting(self.db, SETTING_SALE_KINDS, DEFAULT_SALE_KINDS))
        excluded_statuses = set(
            get_setting(self.db, SETTING_EXCLUDED_STATUSES, DEFAULT_EXCLUDED_STATUSES)
        )
        products = {
            prod.id: prod for prod in self.db.execute(select(Product)).scalars()
        }
        bundles: dict[int, list[ProductBundleComponent]] = {}
        for comp in self.db.execute(select(ProductBundleComponent)).scalars():
            bundles.setdefault(comp.bundle_product_id, []).append(comp)
        warehouse_map = self._warehouse_map()
        default_wh = self._default_warehouse().id

        movements: list[_PendingMovement] = []
        invoices = self.db.execute(
            select(FakturowniaInvoice).where(FakturowniaInvoice.is_deleted_upstream.is_(False))
        ).scalars().all()

        for invoice in invoices:
            if invoice.is_cancelled:
                continue  # cancelled documents never settle stock (see ASSUMPTIONS.md)
            if invoice.invoice_status in excluded_statuses:
                continue
            if invoice.income is False:
                continue  # purchase/cost documents are out of scope for sales control
            is_sale = invoice.kind in sale_kinds
            is_correction = invoice.is_correction
            if not is_sale and not is_correction:
                continue  # proforma / estimate etc. — no stock effect

            occurred = _dt(invoice.sell_date or invoice.issue_date or date.today())
            warehouse_id = warehouse_map.get(invoice.warehouse_fakturownia_id, default_wh)

            for position in invoice.positions:
                if position.mapped_product_id is None:
                    continue  # unmapped positions are reported by validation
                product = products.get(position.mapped_product_id)
                if product is None:
                    continue
                if not product.is_stock_controlled or product.kind in (
                    str(ProductKind.SERVICE), str(ProductKind.IGNORED)
                ):
                    continue
                quantity = position.quantity or ZERO
                if quantity == ZERO:
                    continue

                movement_type = (
                    StockMovementType.SALE_CORRECTION if is_correction
                    else StockMovementType.SALE
                )
                # Sales decrease stock; correction quantities are deltas, so a
                # negative correction quantity puts stock back.
                change = -quantity

                targets: list[tuple[int, Decimal]]
                if product.kind == str(ProductKind.BUNDLE):
                    components = bundles.get(product.id, [])
                    if not components:
                        continue  # bundle without composition → validation issue
                    targets = [
                        (comp.component_product_id, change * comp.quantity)
                        for comp in components
                    ]
                else:
                    targets = [(product.id, change)]

                for target_product_id, target_change in targets:
                    movements.append(
                        _PendingMovement(
                            product_id=target_product_id,
                            warehouse_id=warehouse_id,
                            movement_type=movement_type,
                            quantity_change=target_change,
                            occurred_at=occurred,
                            source_invoice_id=invoice.id,
                            source_invoice_position_id=position.id,
                            description=(
                                f"{'Korekta' if is_correction else 'Sprzedaż'} "
                                f"{invoice.number or invoice.fakturownia_id}: {position.name}"
                            ),
                            priority=7 if not is_correction else 6,
                        )
                    )
        return movements

    def _manual_adjustment_movements(self) -> list[_PendingMovement]:
        result = []
        for adj in self.db.execute(select(LocalStockAdjustment)).scalars():
            result.append(
                _PendingMovement(
                    product_id=adj.product_id,
                    warehouse_id=adj.warehouse_id,
                    movement_type=StockMovementType.MANUAL_ADJUSTMENT,
                    quantity_change=adj.quantity_change,
                    occurred_at=_aware(adj.occurred_at),
                    source_adjustment_id=adj.id,
                    description=adj.description,
                    created_by_user_id=adj.created_by_user_id,
                    priority=3,
                )
            )
        return result

    def _imported_warehouse_action_movements(self) -> list[_PendingMovement]:
        """Optional: use Fakturownia warehouse actions as stock input.

        Disabled by default because sales invoices already settle stock; see
        SETTING_USE_WAREHOUSE_ACTIONS and ASSUMPTIONS.md.
        """
        product_by_fid = {
            prod.fakturownia_product_id: prod.id
            for prod in self.db.execute(select(Product)).scalars()
            if prod.fakturownia_product_id is not None
        }
        warehouse_map = self._warehouse_map()
        default_wh = self._default_warehouse().id
        inbound_kinds = {"pz", "pw", "mm_in", "zw"}
        outbound_kinds = {"wz", "rw", "mm_out"}

        movements = []
        for action in self.db.execute(
            select(WarehouseAction).where(WarehouseAction.is_deleted_upstream.is_(False))
        ).scalars():
            product_id = product_by_fid.get(action.product_fakturownia_id)
            if product_id is None or action.quantity is None:
                continue
            kind = (action.kind or "").lower()
            quantity = action.quantity
            if kind in inbound_kinds:
                change = abs(quantity)
            elif kind in outbound_kinds:
                change = -abs(quantity)
            else:
                change = quantity  # trust the sign as reported
            movements.append(
                _PendingMovement(
                    product_id=product_id,
                    warehouse_id=warehouse_map.get(action.warehouse_fakturownia_id, default_wh),
                    movement_type=StockMovementType.IMPORTED_WAREHOUSE_ACTION,
                    quantity_change=change,
                    occurred_at=_aware(action.occurred_at)
                    if action.occurred_at else datetime.now(timezone.utc),
                    source_warehouse_action_id=action.id,
                    description=f"Import akcji magazynowej {action.fakturownia_id} ({action.kind})",
                    priority=2,
                )
            )
        return movements

    # ------------------------------------------------------------------ #
    # Local write operations (opening balances / adjustments)
    # ------------------------------------------------------------------ #
    def set_opening_balance(
        self,
        product_id: int,
        warehouse_id: int,
        quantity: Decimal,
        as_of_date: date,
        note: str | None,
        user_id: int | None,
    ) -> OpeningBalance:
        existing = self.db.execute(
            select(OpeningBalance).where(
                OpeningBalance.product_id == product_id,
                OpeningBalance.warehouse_id == warehouse_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.quantity = quantity
            existing.as_of_date = as_of_date
            existing.note = note
            existing.created_by_user_id = user_id
            self.db.flush()
            return existing
        balance = OpeningBalance(
            product_id=product_id,
            warehouse_id=warehouse_id,
            quantity=quantity,
            as_of_date=as_of_date,
            note=note,
            created_by_user_id=user_id,
        )
        self.db.add(balance)
        self.db.flush()
        return balance

    def create_adjustment(
        self,
        product_id: int,
        warehouse_id: int,
        quantity_change: Decimal,
        description: str,
        occurred_at: datetime | None,
        user_id: int | None,
        reverses_adjustment_id: int | None = None,
    ) -> LocalStockAdjustment:
        adjustment = LocalStockAdjustment(
            product_id=product_id,
            warehouse_id=warehouse_id,
            quantity_change=quantity_change,
            description=description,
            occurred_at=occurred_at or datetime.now(timezone.utc),
            created_by_user_id=user_id,
            is_reversal=reverses_adjustment_id is not None,
            reverses_adjustment_id=reverses_adjustment_id,
        )
        self.db.add(adjustment)
        self.db.flush()
        return adjustment

    def reverse_adjustment(
        self, adjustment_id: int, user_id: int | None, description: str | None = None
    ) -> LocalStockAdjustment:
        """Reversibility rule: history is never deleted, only compensated."""
        original = self.db.get(LocalStockAdjustment, adjustment_id)
        if original is None:
            raise ValueError(f"Korekta {adjustment_id} nie istnieje")
        return self.create_adjustment(
            product_id=original.product_id,
            warehouse_id=original.warehouse_id,
            quantity_change=-original.quantity_change,
            description=description or f"Storno korekty #{original.id}: {original.description}",
            occurred_at=datetime.now(timezone.utc),
            user_id=user_id,
            reverses_adjustment_id=original.id,
        )
