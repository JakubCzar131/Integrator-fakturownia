from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.database.session import get_db
from app.models.fakturownia import FakturowniaInvoice, FakturowniaInvoicePosition
from app.models.stock import LocalStockLedgerEntry
from app.models.user import User
from app.models.validation import ValidationIssue
from app.repositories.pagination import PageParams, apply_sort, paginate
from app.schemas.common import Page
from app.schemas.domain import InvoiceDetailOut, InvoiceOut, StockLedgerEntryOut, ValidationIssueOut
from app.security.auth import require_any_role
from app.services.report_service import OPEN_ISSUE_STATUSES

router = APIRouter(prefix="/invoices", tags=["invoices"])


def _open_issue_count_subquery():
    return (
        select(
            ValidationIssue.invoice_id.label("invoice_id"),
            func.count(ValidationIssue.id).label("open_issues"),
        )
        .where(ValidationIssue.status.in_(OPEN_ISSUE_STATUSES))
        .group_by(ValidationIssue.invoice_id)
        .subquery()
    )


@router.get("", response_model=Page[InvoiceOut])
def list_invoices(
    params: PageParams = Depends(),
    search: str | None = None,
    number: str | None = None,
    buyer: str | None = None,
    kind: str | None = None,
    invoice_status: str | None = None,
    validation: str | None = None,  # with_issues | clean
    product_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_cancelled: bool = True,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    issues = _open_issue_count_subquery()
    positions_count = (
        select(
            FakturowniaInvoicePosition.invoice_id.label("invoice_id"),
            func.count(FakturowniaInvoicePosition.id).label("position_count"),
        )
        .group_by(FakturowniaInvoicePosition.invoice_id)
        .subquery()
    )
    query = (
        select(
            FakturowniaInvoice,
            func.coalesce(issues.c.open_issues, 0).label("open_issue_count"),
            func.coalesce(positions_count.c.position_count, 0).label("position_count"),
        )
        .outerjoin(issues, issues.c.invoice_id == FakturowniaInvoice.id)
        .outerjoin(positions_count, positions_count.c.invoice_id == FakturowniaInvoice.id)
    )
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                FakturowniaInvoice.number.ilike(pattern),
                FakturowniaInvoice.buyer_name.ilike(pattern),
            )
        )
    if number:
        query = query.where(FakturowniaInvoice.number.ilike(f"%{number}%"))
    if buyer:
        query = query.where(FakturowniaInvoice.buyer_name.ilike(f"%{buyer}%"))
    if kind:
        query = query.where(FakturowniaInvoice.kind == kind)
    if invoice_status:
        query = query.where(FakturowniaInvoice.invoice_status == invoice_status)
    if date_from:
        query = query.where(FakturowniaInvoice.issue_date >= date_from)
    if date_to:
        query = query.where(FakturowniaInvoice.issue_date <= date_to)
    if not include_cancelled:
        query = query.where(FakturowniaInvoice.is_cancelled.is_(False))
    if product_id:
        query = query.where(
            FakturowniaInvoice.id.in_(
                select(FakturowniaInvoicePosition.invoice_id).where(
                    FakturowniaInvoicePosition.mapped_product_id == product_id
                )
            )
        )
    if validation == "with_issues":
        query = query.where(func.coalesce(issues.c.open_issues, 0) > 0)
    elif validation == "clean":
        query = query.where(func.coalesce(issues.c.open_issues, 0) == 0)

    sortable = {
        "id": FakturowniaInvoice.id,
        "number": FakturowniaInvoice.number,
        "issue_date": FakturowniaInvoice.issue_date,
        "sell_date": FakturowniaInvoice.sell_date,
        "buyer_name": FakturowniaInvoice.buyer_name,
        "kind": FakturowniaInvoice.kind,
        "invoice_status": FakturowniaInvoice.invoice_status,
        "total_net": FakturowniaInvoice.total_net,
        "total_gross": FakturowniaInvoice.total_gross,
        "open_issue_count": func.coalesce(issues.c.open_issues, 0),
    }
    if not params.sort_by:
        query = query.order_by(FakturowniaInvoice.issue_date.desc(), FakturowniaInvoice.id.desc())
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)

    items = []
    for invoice, open_issue_count, position_count in result["rows"]:
        out = InvoiceOut.model_validate(invoice)
        out.open_issue_count = open_issue_count
        out.position_count = position_count
        items.append(out)
    return {**{k: result[k] for k in ("total", "page", "per_page", "pages")}, "items": items}


@router.get("/{invoice_id}", response_model=InvoiceDetailOut)
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> InvoiceDetailOut:
    invoice = db.execute(
        select(FakturowniaInvoice)
        .options(selectinload(FakturowniaInvoice.positions))
        .where(FakturowniaInvoice.id == invoice_id)
    ).scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=404, detail="Faktura nie istnieje")
    out = InvoiceDetailOut.model_validate(invoice)
    out.open_issue_count = db.execute(
        select(func.count(ValidationIssue.id)).where(
            ValidationIssue.invoice_id == invoice_id,
            ValidationIssue.status.in_(OPEN_ISSUE_STATUSES),
        )
    ).scalar_one()
    out.position_count = len(invoice.positions)
    return out


@router.get("/{invoice_id}/issues", response_model=list[ValidationIssueOut])
def get_invoice_issues(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> list[ValidationIssueOut]:
    issues = db.execute(
        select(ValidationIssue)
        .where(ValidationIssue.invoice_id == invoice_id)
        .order_by(ValidationIssue.severity, ValidationIssue.id)
    ).scalars().all()
    return [ValidationIssueOut.model_validate(i) for i in issues]


@router.get("/{invoice_id}/ledger", response_model=list[StockLedgerEntryOut])
def get_invoice_ledger(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> list[StockLedgerEntryOut]:
    entries = db.execute(
        select(LocalStockLedgerEntry)
        .where(LocalStockLedgerEntry.source_invoice_id == invoice_id)
        .order_by(LocalStockLedgerEntry.sequence)
    ).scalars().all()
    return [StockLedgerEntryOut.model_validate(e) for e in entries]
