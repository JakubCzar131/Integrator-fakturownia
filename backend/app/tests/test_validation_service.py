from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models.product import Product
from app.models.validation import ValidationIssue
from app.services.mapping_service import apply_position_mappings, confirm_mapping
from app.services.stock_service import StockService
from app.services.sync_service import SyncService
from app.services.validation_service import ValidationService
from app.tests.fixtures import FakeFakturowniaClient


def _prepare(db) -> ValidationService:
    SyncService(db, FakeFakturowniaClient()).run_full_sync()
    db.commit()
    return ValidationService(db)


def _issues(db, issue_type: str) -> list[ValidationIssue]:
    return list(
        db.execute(
            select(ValidationIssue).where(ValidationIssue.issue_type == issue_type)
        ).scalars()
    )


def test_validation_detects_unrecognized_product(db) -> None:
    service = _prepare(db)
    run = service.run_validation()
    assert run.status == "SUCCESS"
    issues = _issues(db, "PRODUCT_NOT_RECOGNIZED")
    assert len(issues) == 1
    assert issues[0].status == "NEEDS_MAPPING"
    assert "Tajemniczy gadżet XYZ" in issues[0].business_description


def test_validation_detects_negative_and_insufficient_stock(db) -> None:
    service = _prepare(db)
    service.run_validation()
    negative = _issues(db, "NEGATIVE_STOCK")
    insufficient = _issues(db, "INSUFFICIENT_STOCK")
    assert negative, "sales without opening balance must produce NEGATIVE_STOCK"
    assert insufficient
    issue = negative[0]
    assert issue.stock_before is not None
    assert issue.stock_after is not None
    assert issue.stock_after < 0
    assert issue.recommended_action


def test_validation_detects_missing_opening_balance(db) -> None:
    service = _prepare(db)
    service.run_validation()
    issues = _issues(db, "MISSING_OPENING_BALANCE")
    assert issues
    assert all(i.status == "NEEDS_OPENING_BALANCE" for i in issues)


def test_opening_balance_resolves_stock_issues(db) -> None:
    service = _prepare(db)
    service.run_validation()
    assert _issues(db, "NEGATIVE_STOCK")

    widget_a = db.execute(select(Product).where(Product.name == "Widget A")).scalar_one()
    widget_b = db.execute(select(Product).where(Product.name == "Widget B")).scalar_one()
    stock = StockService(db)
    stock.set_opening_balance(widget_a.id, 1, Decimal("100"), date(2025, 1, 1), None, None)
    stock.set_opening_balance(widget_b.id, 1, Decimal("100"), date(2025, 1, 1), None, None)
    db.commit()

    service.run_validation()
    still_open = [
        i for i in _issues(db, "NEGATIVE_STOCK") if i.status not in ("RESOLVED", "IGNORED")
    ]
    assert still_open == []
    # previously detected issues must be auto-resolved, not deleted
    assert all(i.status == "RESOLVED" for i in _issues(db, "NEGATIVE_STOCK"))


def test_validation_is_idempotent_no_duplicate_issues(db) -> None:
    service = _prepare(db)
    service.run_validation()
    first = len(db.execute(select(ValidationIssue)).scalars().all())
    service.run_validation()
    second = len(db.execute(select(ValidationIssue)).scalars().all())
    assert first == second


def test_mapping_confirmation_then_revalidation(db) -> None:
    """Acceptance test 19+20: map locally, re-run validation, issue disappears."""
    service = _prepare(db)
    service.run_validation()
    assert any(
        i.status == "NEEDS_MAPPING" for i in _issues(db, "PRODUCT_NOT_RECOGNIZED")
    )

    from app.models.product import ProductMapping

    stub = db.execute(
        select(ProductMapping).where(ProductMapping.source_name == "Tajemniczy gadżet XYZ")
    ).scalar_one()
    widget_b = db.execute(select(Product).where(Product.name == "Widget B")).scalar_one()
    confirm_mapping(db, stub, widget_b.id, user_id=None)
    db.commit()

    service.run_validation()
    open_issues = [
        i for i in _issues(db, "PRODUCT_NOT_RECOGNIZED")
        if i.status not in ("RESOLVED", "IGNORED")
    ]
    assert open_issues == []


def test_cancelled_invoice_not_settled_and_not_flagged(db) -> None:
    service = _prepare(db)
    service.run_validation()
    assert _issues(db, "CANCELLED_INVOICE_INCLUDED") == []


def test_duplicate_invoice_detection(db) -> None:
    invoices = [dict(i) for i in FakeFakturowniaClient().invoices]
    duplicate = {
        **invoices[0], "id": 9999, "updated_at": "2025-01-11T12:00:00Z",
        "positions": [
            {**invoices[0]["positions"][0], "id": 999},
        ],
    }
    invoices.append(duplicate)
    SyncService(db, FakeFakturowniaClient(invoices=invoices)).run_full_sync()
    db.commit()
    ValidationService(db).run_validation()
    issues = _issues(db, "DUPLICATE_INVOICE")
    assert len(issues) == 1


def test_ignored_issue_stays_ignored(db) -> None:
    service = _prepare(db)
    service.run_validation()
    issue = _issues(db, "NEGATIVE_STOCK")[0]
    issue.status = "IGNORED"
    db.commit()
    service.run_validation()
    db.refresh(issue)
    assert issue.status == "IGNORED"


def test_unit_mismatch_detection(db) -> None:
    invoices = [dict(i) for i in FakeFakturowniaClient().invoices]
    invoices[0] = {
        **invoices[0],
        "positions": [
            {**invoices[0]["positions"][0], "quantity_unit": "kg"},
        ],
    }
    SyncService(db, FakeFakturowniaClient(invoices=invoices)).run_full_sync()
    db.commit()
    ValidationService(db).run_validation()
    issues = _issues(db, "UNIT_MISMATCH")
    assert len(issues) == 1
    assert "kg" in issues[0].technical_description


def test_correction_without_original_flagged(db) -> None:
    invoices = [dict(i) for i in FakeFakturowniaClient().invoices]
    for invoice in invoices:
        if invoice["kind"] == "correction":
            invoice["from_invoice_id"] = 424242  # unknown original
    SyncService(db, FakeFakturowniaClient(invoices=invoices)).run_full_sync()
    db.commit()
    ValidationService(db).run_validation()
    assert _issues(db, "CORRECTION_NOT_HANDLED")
