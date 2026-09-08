from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models.product import Product
from app.models.stock import LocalStockBalance, LocalStockLedgerEntry
from app.services.stock_service import StockService
from app.services.sync_service import SyncService
from app.tests.fixtures import FakeFakturowniaClient


def _prepare(db) -> StockService:
    SyncService(db, FakeFakturowniaClient()).run_full_sync()
    return StockService(db)


def _product(db, name: str) -> Product:
    return db.execute(select(Product).where(Product.name == name)).scalar_one()


def _balance(db, product_id: int) -> Decimal:
    balance = db.execute(
        select(LocalStockBalance).where(LocalStockBalance.product_id == product_id)
    ).scalar_one_or_none()
    return balance.quantity if balance else Decimal("0")


def test_sales_decrease_local_stock(db) -> None:
    service = _prepare(db)
    widget_a = _product(db, "Widget A")
    warehouse_id = 1
    service.set_opening_balance(
        widget_a.id, warehouse_id, Decimal("100"), date(2025, 1, 1), "inwentaryzacja", None
    )
    service.rebuild_stock()
    db.commit()
    # 100 (opening) - 10 (FV 1/2025) + 2 (correction KOR 1/2025) = 92
    # cancelled FV 4/2025 (5 szt) must NOT be settled
    assert _balance(db, widget_a.id) == Decimal("92")


def test_correction_invoice_returns_stock(db) -> None:
    service = _prepare(db)
    widget_a = _product(db, "Widget A")
    service.set_opening_balance(
        widget_a.id, 1, Decimal("10"), date(2025, 1, 1), None, None
    )
    service.rebuild_stock()
    entries = db.execute(
        select(LocalStockLedgerEntry).where(
            LocalStockLedgerEntry.product_id == widget_a.id,
            LocalStockLedgerEntry.movement_type == "SALE_CORRECTION",
        )
    ).scalars().all()
    assert len(entries) == 1
    assert entries[0].quantity_change == Decimal("2")  # -(-2)


def test_services_do_not_move_stock(db) -> None:
    service = _prepare(db)
    montaz = _product(db, "Usługa montażu")
    service.rebuild_stock()
    entries = db.execute(
        select(LocalStockLedgerEntry).where(
            LocalStockLedgerEntry.product_id == montaz.id
        )
    ).scalars().all()
    assert entries == []


def test_negative_stock_detected_without_opening_balance(db) -> None:
    service = _prepare(db)
    widget_a = _product(db, "Widget A")
    stats = service.rebuild_stock()
    assert stats["negative_balances"] >= 1
    assert _balance(db, widget_a.id) == Decimal("-8")  # 0 - 10 + 2


def test_manual_adjustment_and_reversal(db) -> None:
    service = _prepare(db)
    widget_b = _product(db, "Widget B")
    adjustment = service.create_adjustment(
        product_id=widget_b.id, warehouse_id=1,
        quantity_change=Decimal("50"), description="Dostawa poza systemem",
        occurred_at=datetime(2025, 1, 1, tzinfo=timezone.utc), user_id=None,
    )
    service.rebuild_stock()
    assert _balance(db, widget_b.id) == Decimal("38")  # +50 - 12 (FV 2/2025)

    service.reverse_adjustment(adjustment.id, user_id=None)
    service.rebuild_stock()
    assert _balance(db, widget_b.id) == Decimal("-12")


def test_ledger_balances_are_consistent(db) -> None:
    service = _prepare(db)
    widget_a = _product(db, "Widget A")
    service.set_opening_balance(
        widget_a.id, 1, Decimal("30"), date(2025, 1, 1), None, None
    )
    service.rebuild_stock()
    entries = db.execute(
        select(LocalStockLedgerEntry)
        .where(LocalStockLedgerEntry.product_id == widget_a.id)
        .order_by(LocalStockLedgerEntry.sequence)
    ).scalars().all()
    running = Decimal("0")
    for entry in entries:
        assert entry.balance_before == running
        running += entry.quantity_change
        assert entry.balance_after == running


def test_rebuild_is_deterministic(db) -> None:
    service = _prepare(db)
    widget_a = _product(db, "Widget A")
    service.set_opening_balance(
        widget_a.id, 1, Decimal("100"), date(2025, 1, 1), None, None
    )
    stats1 = service.rebuild_stock()
    balance1 = _balance(db, widget_a.id)
    stats2 = service.rebuild_stock()
    assert stats1["movements"] == stats2["movements"]
    assert _balance(db, widget_a.id) == balance1


def test_bundle_sale_expands_to_components(db) -> None:
    from app.models.product import ProductBundleComponent

    service = _prepare(db)
    widget_a = _product(db, "Widget A")
    widget_b = _product(db, "Widget B")
    bundle = Product(name="Zestaw AB", kind="BUNDLE", is_stock_controlled=True)
    db.add(bundle)
    db.flush()
    db.add(ProductBundleComponent(
        bundle_product_id=bundle.id, component_product_id=widget_a.id,
        quantity=Decimal("2"),
    ))
    db.add(ProductBundleComponent(
        bundle_product_id=bundle.id, component_product_id=widget_b.id,
        quantity=Decimal("1"),
    ))
    # Map the unknown position "Tajemniczy gadżet XYZ" (qty 2) to the bundle.
    from app.models.fakturownia import FakturowniaInvoicePosition

    position = db.execute(
        select(FakturowniaInvoicePosition).where(FakturowniaInvoicePosition.fakturownia_id == 4)
    ).scalar_one()
    position.mapped_product_id = bundle.id
    position.mapping_status = "CONFIRMED"
    db.flush()

    service.rebuild_stock()
    bundle_entries = db.execute(
        select(LocalStockLedgerEntry).where(
            LocalStockLedgerEntry.source_invoice_position_id == position.id
        )
    ).scalars().all()
    changes = {e.product_id: e.quantity_change for e in bundle_entries}
    assert changes[widget_a.id] == Decimal("-4")  # 2 szt zestawu × 2 komponenty
    assert changes[widget_b.id] == Decimal("-2")
