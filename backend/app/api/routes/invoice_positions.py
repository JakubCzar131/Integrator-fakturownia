from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.fakturownia import FakturowniaInvoice, FakturowniaInvoicePosition
from app.models.user import User
from app.models.validation import ValidationIssue
from app.repositories.pagination import PageParams, apply_sort, paginate
from app.schemas.common import Page
from app.schemas.domain import InvoicePositionListItem
from app.security.auth import require_any_role
from app.services.report_service import OPEN_ISSUE_STATUSES

router = APIRouter(prefix="/invoice-positions", tags=["invoice-positions"])


@router.get("", response_model=Page[InvoicePositionListItem])
def list_positions(
    params: PageParams = Depends(),
    search: str | None = None,
    mapping_status: str | None = None,  # CONFIRMED | PROPOSED | REJECTED | UNMAPPED
    product_id: int | None = None,
    invoice_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    issues = (
        select(
            ValidationIssue.invoice_position_id.label("position_id"),
            func.count(ValidationIssue.id).label("open_issues"),
        )
        .where(ValidationIssue.status.in_(OPEN_ISSUE_STATUSES))
        .group_by(ValidationIssue.invoice_position_id)
        .subquery()
    )
    query = (
        select(
            FakturowniaInvoicePosition,
            FakturowniaInvoice.number,
            FakturowniaInvoice.issue_date,
            FakturowniaInvoice.kind,
            FakturowniaInvoice.buyer_name,
            func.coalesce(issues.c.open_issues, 0).label("open_issues"),
        )
        .join(FakturowniaInvoice, FakturowniaInvoice.id == FakturowniaInvoicePosition.invoice_id)
        .outerjoin(issues, issues.c.position_id == FakturowniaInvoicePosition.id)
    )
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                FakturowniaInvoicePosition.name.ilike(pattern),
                FakturowniaInvoicePosition.code.ilike(pattern),
                FakturowniaInvoice.number.ilike(pattern),
            )
        )
    if mapping_status == "UNMAPPED":
        query = query.where(FakturowniaInvoicePosition.mapped_product_id.is_(None))
    elif mapping_status:
        query = query.where(FakturowniaInvoicePosition.mapping_status == mapping_status)
    if product_id:
        query = query.where(FakturowniaInvoicePosition.mapped_product_id == product_id)
    if invoice_id:
        query = query.where(FakturowniaInvoicePosition.invoice_id == invoice_id)

    sortable = {
        "id": FakturowniaInvoicePosition.id,
        "name": FakturowniaInvoicePosition.name,
        "quantity": FakturowniaInvoicePosition.quantity,
        "price_net": FakturowniaInvoicePosition.price_net,
        "total_price_net": FakturowniaInvoicePosition.total_price_net,
        "invoice_number": FakturowniaInvoice.number,
        "invoice_issue_date": FakturowniaInvoice.issue_date,
        "mapping_status": FakturowniaInvoicePosition.mapping_status,
        "open_issue_count": func.coalesce(issues.c.open_issues, 0),
    }
    if not params.sort_by:
        query = query.order_by(FakturowniaInvoice.issue_date.desc(), FakturowniaInvoicePosition.id.desc())
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)

    items = []
    for position, number, issue_date, kind, buyer_name, open_issues in result["rows"]:
        item = InvoicePositionListItem.model_validate(position)
        item.invoice_number = number
        item.invoice_issue_date = issue_date
        item.invoice_kind = kind
        item.buyer_name = buyer_name
        item.open_issue_count = open_issues
        items.append(item)
    return {**{k: result[k] for k in ("total", "page", "per_page", "pages")}, "items": items}
