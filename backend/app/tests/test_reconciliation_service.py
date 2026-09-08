"""Reconciliation table: Fakturownia stock vs PZ/PW receipts vs sales invoices."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.models.product import Product
from app.models.reconciliation import ReconciliationRun, StockReconciliationLine
from app.models.settings import AppSetting
from app.services.reconciliation_service import (
    SETTING_INCLUDE_OUTBOUND_DOCUMENTS,
    SETTING_KEEP_RUNS,
    ReconciliationService,
    reconciled_stock_map,
)
from app.services.stock_service import StockService
from app.services.sync_service import SyncService
from app.services.validation_service import SETTING_DISCREPANCY_TOLERANCE
from app.tests.fixtures import FAKE_WAREHOUSE_DOCUMENTS, FakeFakturowniaClient


def _set(db, key: str, value) -> None:
    row = db.execute(select(AppSetting).where(AppSetting.key == key)).scalar_one_or_none()
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    db.flush()


def _sync(db, **client_kwargs) -> None:
    SyncService(db, FakeFakturowniaClient(**client_kwargs)).run_full_sync()


def _product(db, name: str) -> Product:
    return db.execute(select(Product).where(Product.name == name)).scalar_one()


def _lines(db, run: ReconciliationRun) -> dict[str, StockReconciliationLine]:
    rows = db.execute(
        select(StockReconciliationLine, Product.name)
        .join(Product, Product.id == StockReconciliationLine.product_id)
        .where(StockReconciliationLine.run_id == run.id)
    ).all()
    return {name: line for line, name in rows}


def test_sync_materializes_a_snapshot_automatically(db) -> None:
    _sync(db)
    run = ReconciliationService(db).latest_run()
    assert run is not None
    assert run.trigger == "SYNC"
    assert run.sync_run_id is not None
    assert run.finished_at is not None
    assert run.duration_seconds is not None


def test_receipts_are_split_between_pz_and_pw(db) -> None:
    _sync(db)
    lines = _lines(db, ReconciliationService(db).latest_run())

    widget_a = lines["Widget A"]
    # PZ 1/2025 delivered 20 pcs (through a warehouse action).
    assert widget_a.inbound_pz == Decimal("20.0000")
    # PW 1/2025 added 5 more pcs (recognized by code, no product_id).
    assert widget_a.inbound_pw == Decimal("5.0000")

    widget_b = lines["Widget B"]
    assert widget_b.inbound_pz == Decimal("0.0000")
    assert widget_b.inbound_pw == Decimal("30.0000")


def test_sales_and_corrections_are_settled_against_receipts(db) -> None:
    _sync(db)
    lines = _lines(db, ReconciliationService(db).latest_run())

    widget_a = lines["Widget A"]
    assert widget_a.sold_invoices == Decimal("10.0000")  # FV 1/2025
    # KOR 1/2025 returns 2 pcs; Fakturownia reports the delta as -2.
    assert widget_a.corrections == Decimal("-2.0000")
    # 0 opening + 20 PZ + 5 PW − 10 sold − (−2) returned = 17
    assert widget_a.computed_stock == Decimal("17.0000")
    assert widget_a.fakturownia_stock == Decimal("50.0000")
    assert widget_a.difference == Decimal("-33.0000")
    assert widget_a.status == "DISCREPANCY"

    # The cancelled FV 4/2025 (5 pcs of Widget A) must not settle anything.
    assert widget_a.sold_invoices == Decimal("10.0000")


def test_opening_balance_enters_the_computation(db) -> None:
    _sync(db)
    widget_a = _product(db, "Widget A")
    StockService(db).set_opening_balance(
        widget_a.id, 1, Decimal("33"), date(2025, 1, 1), "inwentaryzacja", None
    )
    run = ReconciliationService(db).refresh()

    line = _lines(db, run)["Widget A"]
    assert line.opening_balance == Decimal("33.0000")
    assert line.computed_stock == Decimal("50.0000")  # 33 + 20 + 5 − 10 + 2
    assert line.difference == Decimal("0.0000")
    assert line.status == "OK"


def test_products_without_remote_stock_are_flagged_not_compared(db) -> None:
    _sync(db)
    line = _lines(db, ReconciliationService(db).latest_run())["Usługa montażu"]
    assert line.fakturownia_stock is None
    assert line.difference is None
    assert line.status == "NO_REMOTE_STOCK"


def test_run_counters_match_the_materialized_lines(db) -> None:
    _sync(db)
    run = ReconciliationService(db).latest_run()
    lines = _lines(db, run)
    assert run.line_count == len(lines)
    assert run.discrepancy_count == sum(
        1 for line in lines.values() if line.status == "DISCREPANCY"
    )
    assert run.stats["products"] == len(lines)


def test_outbound_documents_are_informational_by_default(db) -> None:
    """A WZ usually accompanies the sales invoice — counting both double-settles."""
    documents = [dict(document) for document in FAKE_WAREHOUSE_DOCUMENTS]
    documents.append(
        {"id": 7003, "kind": "WZ", "number": "WZ 1/2025", "warehouse_id": 900,
         "issue_date": "2025-01-10",
         "positions": [
             {"id": 8201, "product_id": 101, "name": "Widget A", "quantity": "10"},
         ]}
    )
    _sync(db, warehouse_documents=documents)

    line = _lines(db, ReconciliationService(db).latest_run())["Widget A"]
    assert line.outbound_documents == Decimal("10.0000")
    assert line.computed_stock == Decimal("17.0000")  # unchanged by the WZ

    _set(db, SETTING_INCLUDE_OUTBOUND_DOCUMENTS, True)
    line = _lines(db, ReconciliationService(db).refresh())["Widget A"]
    assert line.computed_stock == Decimal("7.0000")


def test_tolerance_decides_between_ok_and_discrepancy(db) -> None:
    _sync(db)
    widget_b = _product(db, "Widget B")
    # 0 + 30 PW − 12 sold = 18 computed vs 5 reported → difference of 13.
    _set(db, SETTING_DISCREPANCY_TOLERANCE, "20")
    line = _lines(db, ReconciliationService(db).refresh())["Widget B"]
    assert line.difference == Decimal("13.0000")
    assert line.status == "OK"
    assert line.product_id == widget_b.id


def test_refresh_is_repeatable_and_keeps_history(db) -> None:
    _sync(db)
    first = ReconciliationService(db).latest_run()
    second = ReconciliationService(db).refresh(trigger="MANUAL")
    assert second.id != first.id
    assert second.line_count == first.line_count
    assert db.execute(select(func.count(ReconciliationRun.id))).scalar_one() == 2
    # Each run owns its own lines, so the trend stays reconstructable.
    assert len(_lines(db, first)) == len(_lines(db, second))


def test_history_is_pruned_to_the_configured_depth(db) -> None:
    _sync(db)
    _set(db, SETTING_KEEP_RUNS, 2)
    service = ReconciliationService(db)
    for _ in range(3):
        service.refresh()
    db.flush()
    assert db.execute(select(func.count(ReconciliationRun.id))).scalar_one() == 2
    # Lines of pruned runs go with them (cascade), leaving no orphans.
    live_run_ids = {row[0] for row in db.execute(select(ReconciliationRun.id)).all()}
    line_run_ids = {
        row[0] for row in db.execute(select(StockReconciliationLine.run_id)).all()
    }
    assert line_run_ids <= live_run_ids


def test_reconciled_stock_map_sums_over_warehouses(db) -> None:
    _sync(db)
    widget_a = _product(db, "Widget A")
    stock = reconciled_stock_map(db)
    assert stock[widget_a.id] == Decimal("17.0000")


def test_no_snapshot_means_an_empty_stock_map(db) -> None:
    assert reconciled_stock_map(db) == {}


# ------------------------------- API ----------------------------------- #
def test_api_serves_the_latest_snapshot_with_filters(client, admin_headers, seeded_db) -> None:
    _sync(seeded_db)
    response = client.get("/api/v1/reconciliation", headers=admin_headers)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert {item["product_name"] for item in items} == {
        "Widget A", "Widget B", "Usługa montażu"
    }
    assert all(item["warehouse_name"] == "Magazyn centralny" for item in items)

    discrepancies = client.get(
        "/api/v1/reconciliation?only_discrepancies=true", headers=admin_headers
    ).json()
    assert discrepancies["total"] == 2

    searched = client.get(
        "/api/v1/reconciliation?search=Widget B", headers=admin_headers
    ).json()
    assert [item["product_name"] for item in searched["items"]] == ["Widget B"]


def test_api_returns_empty_page_before_the_first_run(client, admin_headers) -> None:
    response = client.get("/api/v1/reconciliation", headers=admin_headers)
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "per_page": 50, "pages": 1}


def test_api_refresh_records_a_run_and_audits_it(client, admin_headers, seeded_db) -> None:
    _sync(seeded_db)
    response = client.post("/api/v1/reconciliation/refresh", headers=admin_headers)
    assert response.status_code == 200, response.text
    detail = response.json()["detail"]
    assert detail["line_count"] == 3
    assert detail["discrepancy_count"] == 2

    runs = client.get("/api/v1/reconciliation/runs", headers=admin_headers).json()
    assert runs["total"] == 2
    assert runs["items"][0]["trigger"] == "MANUAL"

    summary = client.get("/api/v1/reconciliation/summary", headers=admin_headers).json()
    assert summary["run"]["id"] == detail["run_id"]


def test_api_requires_authentication(client) -> None:
    assert client.get("/api/v1/reconciliation").status_code == 401
    assert client.post("/api/v1/reconciliation/refresh").status_code == 401
