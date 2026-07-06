from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.audit.service import record_audit
from app.database.session import get_db
from app.models.enums import AuditAction, ValidationStatus
from app.models.fakturownia import FakturowniaInvoice, Warehouse
from app.models.product import Product
from app.models.user import User
from app.models.validation import ValidationIssue, ValidationIssueComment, ValidationRun
from app.repositories.pagination import PageParams, apply_sort, paginate
from app.schemas.common import Page
from app.schemas.domain import (
    IssueCommentCreate,
    IssueCommentOut,
    ValidationIssueOut,
    ValidationIssueUpdate,
    ValidationRunOut,
)
from app.security.auth import client_ip, require_any_role, require_operator
from app.services.validation_service import ValidationService

router = APIRouter(prefix="/validation", tags=["validation"])


@router.post("/run", response_model=ValidationRunOut)
def run_validation(
    request: Request,
    rebuild_stock: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> ValidationRunOut:
    record_audit(
        db, AuditAction.VALIDATION_STARTED, user=user, object_type="validation",
        description="Uruchomiono walidację sprzedaży",
        ip_address=client_ip(request),
    )
    db.commit()
    service = ValidationService(db)
    run = service.run_validation(user=user, rebuild_stock=rebuild_stock)
    record_audit(
        db, AuditAction.VALIDATION_FINISHED, user=user, object_type="validation",
        object_id=run.id, description=run.message,
        ip_address=client_ip(request),
    )
    db.commit()
    return ValidationRunOut.model_validate(run)


@router.get("/runs", response_model=Page[ValidationRunOut])
def list_validation_runs(
    params: PageParams = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    query = select(ValidationRun)
    sortable = {"id": ValidationRun.id, "started_at": ValidationRun.started_at}
    if not params.sort_by:
        query = query.order_by(ValidationRun.id.desc())
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)
    return {
        **{k: result[k] for k in ("total", "page", "per_page", "pages")},
        "items": [ValidationRunOut.model_validate(row[0]) for row in result["rows"]],
    }


def _issue_query():
    invoice = aliased(FakturowniaInvoice)
    return (
        select(ValidationIssue, invoice.number, Product.name, Warehouse.name)
        .outerjoin(invoice, invoice.id == ValidationIssue.invoice_id)
        .outerjoin(Product, Product.id == ValidationIssue.product_id)
        .outerjoin(Warehouse, Warehouse.id == ValidationIssue.warehouse_id)
    ), invoice


@router.get("/issues", response_model=Page[ValidationIssueOut])
def list_issues(
    params: PageParams = Depends(),
    status: str | None = None,
    issue_type: str | None = None,
    severity: str | None = None,
    invoice_id: int | None = None,
    product_id: int | None = None,
    warehouse_id: int | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    query, invoice = _issue_query()
    if status:
        query = query.where(ValidationIssue.status.in_(status.split(",")))
    if issue_type:
        query = query.where(ValidationIssue.issue_type == issue_type)
    if severity:
        query = query.where(ValidationIssue.severity == severity)
    if invoice_id:
        query = query.where(ValidationIssue.invoice_id == invoice_id)
    if product_id:
        query = query.where(ValidationIssue.product_id == product_id)
    if warehouse_id:
        query = query.where(ValidationIssue.warehouse_id == warehouse_id)
    if search:
        pattern = f"%{search}%"
        query = query.where(
            ValidationIssue.business_description.ilike(pattern)
            | invoice.number.ilike(pattern)
            | Product.name.ilike(pattern)
        )

    sortable = {
        "id": ValidationIssue.id,
        "issue_type": ValidationIssue.issue_type,
        "status": ValidationIssue.status,
        "severity": ValidationIssue.severity,
        "created_at": ValidationIssue.created_at,
        "quantity": ValidationIssue.quantity,
        "invoice_number": invoice.number,
        "product_name": Product.name,
    }
    if not params.sort_by:
        query = query.order_by(ValidationIssue.severity, ValidationIssue.id.desc())
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)

    items = []
    for issue, invoice_number, product_name, warehouse_name in result["rows"]:
        out = ValidationIssueOut.model_validate(issue)
        out.invoice_number = invoice_number
        out.product_name = product_name
        out.warehouse_name = warehouse_name
        items.append(out)
    return {**{k: result[k] for k in ("total", "page", "per_page", "pages")}, "items": items}


@router.get("/issues/summary")
def issues_summary(
    db: Session = Depends(get_db), _: User = Depends(require_any_role)
) -> dict:
    by_status = dict(
        db.execute(
            select(ValidationIssue.status, func.count(ValidationIssue.id))
            .group_by(ValidationIssue.status)
        ).all()
    )
    by_type = dict(
        db.execute(
            select(ValidationIssue.issue_type, func.count(ValidationIssue.id))
            .group_by(ValidationIssue.issue_type)
        ).all()
    )
    return {"by_status": by_status, "by_type": by_type}


@router.get("/issues/{issue_id}", response_model=ValidationIssueOut)
def get_issue(
    issue_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> ValidationIssueOut:
    query, _invoice = _issue_query()
    row = db.execute(query.where(ValidationIssue.id == issue_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Problem walidacyjny nie istnieje")
    issue, invoice_number, product_name, warehouse_name = row
    out = ValidationIssueOut.model_validate(issue)
    out.invoice_number = invoice_number
    out.product_name = product_name
    out.warehouse_name = warehouse_name
    return out


@router.patch("/issues/{issue_id}", response_model=ValidationIssueOut)
def update_issue(
    issue_id: int,
    payload: ValidationIssueUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> ValidationIssueOut:
    """Change issue status (local only)."""
    issue = db.get(ValidationIssue, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Problem walidacyjny nie istnieje")
    old_status = issue.status
    issue.status = payload.status
    if payload.status == str(ValidationStatus.RESOLVED):
        issue.resolved_at = datetime.now(timezone.utc)
        issue.resolved_by_user_id = user.id
    elif old_status == str(ValidationStatus.RESOLVED):
        issue.resolved_at = None
        issue.resolved_by_user_id = None
    record_audit(
        db, AuditAction.UPDATE, user=user, object_type="validation_issue",
        object_id=issue.id,
        description=f"Zmieniono status problemu #{issue.id} ({issue.issue_type})",
        old_value={"status": old_status},
        new_value={"status": payload.status},
        ip_address=client_ip(request),
    )
    db.commit()
    return get_issue(issue_id, db, user)


@router.post("/issues/{issue_id}/comments", response_model=IssueCommentOut, status_code=201)
def add_comment(
    issue_id: int,
    payload: IssueCommentCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> ValidationIssueComment:
    """Add a LOCAL comment to a validation issue."""
    issue = db.get(ValidationIssue, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Problem walidacyjny nie istnieje")
    comment = ValidationIssueComment(
        issue_id=issue_id, user_id=user.id, user_email=user.email, body=payload.body
    )
    db.add(comment)
    db.flush()
    record_audit(
        db, AuditAction.CREATE, user=user, object_type="validation_issue_comment",
        object_id=comment.id,
        description=f"Dodano komentarz do problemu #{issue_id}",
        new_value={"body": payload.body},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(comment)
    return comment
