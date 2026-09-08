from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.enums import ValidationStatus
from app.models.fakturownia import (
    FakturowniaClient as FakturowniaClientRow,
    FakturowniaInvoice,
    FakturowniaInvoicePosition,
    Warehouse,
)
from app.models.product import Product
from app.models.stock import LocalStockBalance
from app.models.sync import SyncRun
from app.models.user import User
from app.models.validation import ValidationIssue, ValidationRun
from app.schemas.domain import DashboardOut, SyncRunOut, ValidationRunOut
from app.security.auth import require_any_role
from app.services.report_service import OPEN_ISSUE_STATUSES

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _count(db: Session, query) -> int:
    return db.execute(select(func.count()).select_from(query.subquery())).scalar_one()


@router.get("", response_model=DashboardOut)
def get_dashboard(
    db: Session = Depends(get_db), _: User = Depends(require_any_role)
) -> DashboardOut:
    last_sync = db.execute(
        select(SyncRun).order_by(SyncRun.id.desc()).limit(1)
    ).scalars().first()
    last_validation = db.execute(
        select(ValidationRun).order_by(ValidationRun.id.desc()).limit(1)
    ).scalars().first()

    status_counts = dict(
        db.execute(
            select(ValidationIssue.status, func.count(ValidationIssue.id))
            .group_by(ValidationIssue.status)
        ).all()
    )
    type_counts = db.execute(
        select(ValidationIssue.issue_type, func.count(ValidationIssue.id))
        .where(ValidationIssue.status.in_(OPEN_ISSUE_STATUSES))
        .group_by(ValidationIssue.issue_type)
        .order_by(func.count(ValidationIssue.id).desc())
    ).all()

    attention = db.execute(
        select(
            FakturowniaInvoice.id,
            FakturowniaInvoice.number,
            FakturowniaInvoice.issue_date,
            FakturowniaInvoice.buyer_name,
            func.count(ValidationIssue.id).label("issues"),
        )
        .join(ValidationIssue, ValidationIssue.invoice_id == FakturowniaInvoice.id)
        .where(ValidationIssue.status.in_(OPEN_ISSUE_STATUSES))
        .group_by(
            FakturowniaInvoice.id, FakturowniaInvoice.number,
            FakturowniaInvoice.issue_date, FakturowniaInvoice.buyer_name,
        )
        .order_by(func.count(ValidationIssue.id).desc())
        .limit(10)
    ).all()

    return DashboardOut(
        last_sync=SyncRunOut.model_validate(last_sync) if last_sync else None,
        last_validation=(
            ValidationRunOut.model_validate(last_validation) if last_validation else None
        ),
        invoice_count=_count(db, select(FakturowniaInvoice.id)),
        position_count=_count(db, select(FakturowniaInvoicePosition.id)),
        product_count=_count(db, select(Product.id)),
        client_count=_count(db, select(FakturowniaClientRow.id)),
        warehouse_count=_count(db, select(Warehouse.id)),
        error_count=status_counts.get(str(ValidationStatus.ERROR), 0),
        warning_count=status_counts.get(str(ValidationStatus.WARNING), 0),
        needs_mapping_count=status_counts.get(str(ValidationStatus.NEEDS_MAPPING), 0),
        needs_opening_balance_count=status_counts.get(
            str(ValidationStatus.NEEDS_OPENING_BALANCE), 0
        ),
        unmapped_position_count=_count(
            db,
            select(FakturowniaInvoicePosition.id).where(
                FakturowniaInvoicePosition.mapped_product_id.is_(None)
            ),
        ),
        negative_stock_count=_count(
            db, select(LocalStockBalance.id).where(LocalStockBalance.quantity < 0)
        ),
        invoices_needing_attention=[
            {
                "id": row.id, "number": row.number,
                "issue_date": row.issue_date.isoformat() if row.issue_date else None,
                "buyer_name": row.buyer_name, "open_issues": row.issues,
            }
            for row in attention
        ],
        issue_type_breakdown=[
            {"issue_type": t, "count": c} for t, c in type_counts
        ],
    )
