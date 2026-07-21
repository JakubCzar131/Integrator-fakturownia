from __future__ import annotations

from sqlalchemy import func, select

from app.models.fakturownia import (
    FakturowniaClient as FakturowniaClientRow,
    FakturowniaInvoice,
    FakturowniaInvoicePosition,
    FakturowniaProduct,
    Warehouse,
    WarehouseAction,
    WarehouseDocument,
)
from app.models.product import Product, ProductMapping
from app.models.sync import SourceSnapshot, SyncRun
from app.services.sync_service import SyncService
from app.tests.fixtures import FakeFakturowniaClient


def _run_full_sync(db) -> SyncRun:
    service = SyncService(db, FakeFakturowniaClient())
    return service.run_full_sync()


def test_full_sync_imports_all_resources(db) -> None:
    run = _run_full_sync(db)
    assert run.status == "SUCCESS", run.errors
    assert db.execute(select(func.count(FakturowniaInvoice.id))).scalar_one() == 5
    assert db.execute(select(func.count(FakturowniaInvoicePosition.id))).scalar_one() == 6
    assert db.execute(select(func.count(FakturowniaProduct.id))).scalar_one() == 3
    assert db.execute(select(func.count(FakturowniaClientRow.id))).scalar_one() == 2
    assert db.execute(select(func.count(Warehouse.id))).scalar_one() == 1
    assert db.execute(select(func.count(WarehouseDocument.id))).scalar_one() == 1
    assert db.execute(select(func.count(WarehouseAction.id))).scalar_one() == 1


def test_full_sync_stores_raw_snapshots(db) -> None:
    _run_full_sync(db)
    snapshots = db.execute(select(SourceSnapshot)).scalars().all()
    assert snapshots
    invoice_snapshots = [s for s in snapshots if s.resource_type == "invoice"]
    assert len(invoice_snapshots) == 5
    assert invoice_snapshots[0].payload["number"].startswith(("FV", "KOR"))
    assert all(len(s.payload_hash) == 64 for s in snapshots)


def test_sync_is_idempotent_no_duplicates(db) -> None:
    _run_full_sync(db)
    first_count = db.execute(select(func.count(FakturowniaInvoice.id))).scalar_one()
    run2 = _run_full_sync(db)
    assert run2.status == "SUCCESS"
    assert db.execute(select(func.count(FakturowniaInvoice.id))).scalar_one() == first_count
    assert db.execute(select(func.count(FakturowniaInvoicePosition.id))).scalar_one() == 6
    # Second run should detect all records as unchanged (no snapshot growth for invoices).
    assert run2.records_unchanged > 0
    invoice_snapshots = db.execute(
        select(func.count(SourceSnapshot.id)).where(SourceSnapshot.resource_type == "invoice")
    ).scalar_one()
    assert invoice_snapshots == 5


def test_sync_detects_upstream_changes(db) -> None:
    _run_full_sync(db)
    changed_invoices = [dict(i) for i in FakeFakturowniaClient().invoices]
    changed_invoices[0] = {**changed_invoices[0], "status": "paid", "price_gross": "999.99"}
    service = SyncService(db, FakeFakturowniaClient(invoices=changed_invoices))
    run = service.run_full_sync()
    assert run.status == "SUCCESS"
    invoice = db.execute(
        select(FakturowniaInvoice).where(FakturowniaInvoice.fakturownia_id == 9001)
    ).scalar_one()
    assert float(invoice.total_gross) == 999.99


def test_full_sync_marks_deleted_upstream(db) -> None:
    _run_full_sync(db)
    remaining = [i for i in FakeFakturowniaClient().invoices if i["id"] != 9003]
    SyncService(db, FakeFakturowniaClient(invoices=remaining)).run_full_sync()
    invoice = db.execute(
        select(FakturowniaInvoice).where(FakturowniaInvoice.fakturownia_id == 9003)
    ).scalar_one()
    assert invoice.is_deleted_upstream is True


def test_sync_creates_local_products_and_mappings(db) -> None:
    _run_full_sync(db)
    products = db.execute(select(Product)).scalars().all()
    assert len(products) == 3
    service_product = next(p for p in products if p.name == "Usługa montażu")
    assert service_product.kind == "SERVICE"
    assert service_product.is_stock_controlled is False

    positions = {
        p.fakturownia_id: p
        for p in db.execute(select(FakturowniaInvoicePosition)).scalars()
    }
    # product_id present -> CONFIRMED via PRODUCT_ID
    assert positions[1].mapping_status == "CONFIRMED"
    assert positions[1].mapping_match_type == "PRODUCT_ID"
    # no product_id but exact code match -> PROPOSED
    assert positions[2].mapped_product_id is not None
    assert positions[2].mapping_status == "PROPOSED"
    # unknown position -> unmapped + mapping stub for the panel
    assert positions[4].mapped_product_id is None
    stub = db.execute(
        select(ProductMapping).where(ProductMapping.source_name == "Tajemniczy gadżet XYZ")
    ).scalar_one()
    assert stub.status == "PROPOSED"
    assert stub.product_id is None


def test_incremental_sync_runs_and_updates(db) -> None:
    _run_full_sync(db)
    service = SyncService(db, FakeFakturowniaClient())
    run = service.run_incremental_sync()
    assert run.status == "SUCCESS"
    assert run.run_type == "INCREMENTAL"
    assert db.execute(select(func.count(FakturowniaInvoice.id))).scalar_one() == 5
