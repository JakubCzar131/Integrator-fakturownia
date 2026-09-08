"""Document reconciliation table: Fakturownia stock vs PZ/PW receipts vs sales.

Reads always serve the latest materialized snapshot, so filtering, sorting and
pagination hit an indexed table instead of recomputing aggregates.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.database.session import get_db
from app.models.enums import AuditAction, ReconciliationStatus
from app.models.fakturownia import Warehouse
from app.models.product import Product
from app.models.reconciliation import ReconciliationRun, StockReconciliationLine
from app.models.user import User
from app.repositories.pagination import PageParams, apply_sort, paginate
from app.schemas.common import MessageResponse, Page
from app.schemas.integrations import ReconciliationLineOut, ReconciliationRunOut
from app.security.auth import client_ip, require_any_role, require_operator
from app.services.reconciliation_service import ReconciliationService

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


@router.get("", response_model=Page[ReconciliationLineOut])
def list_reconciliation(
    params: PageParams = Depends(),
    run_id: int | None = None,
    search: str | None = None,
    warehouse_id: int | None = None,
    status: str | None = None,
    only_discrepancies: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    service = ReconciliationService(db)
    if run_id is None:
        run = service.latest_run()
        if run is None:
            return {"items": [], "total": 0, "page": params.page,
                    "per_page": params.per_page, "pages": 1}
        run_id = run.id

    query = (
        select(
            StockReconciliationLine,
            Product.name,
            Product.code,
            Product.unit,
            Warehouse.name,
        )
        .join(Product, Product.id == StockReconciliationLine.product_id)
        .outerjoin(Warehouse, Warehouse.id == StockReconciliationLine.warehouse_id)
        .where(StockReconciliationLine.run_id == run_id)
    )
    if search:
        pattern = f"%{search}%"
        query = query.where(or_(Product.name.ilike(pattern), Product.code.ilike(pattern)))
    if warehouse_id:
        query = query.where(StockReconciliationLine.warehouse_id == warehouse_id)
    if status:
        query = query.where(StockReconciliationLine.status == status)
    if only_discrepancies:
        query = query.where(
            StockReconciliationLine.status == str(ReconciliationStatus.DISCREPANCY)
        )

    sortable = {
        "product_name": Product.name,
        "warehouse_name": Warehouse.name,
        "fakturownia_stock": StockReconciliationLine.fakturownia_stock,
        "inbound_pz": StockReconciliationLine.inbound_pz,
        "inbound_pw": StockReconciliationLine.inbound_pw,
        "sold_invoices": StockReconciliationLine.sold_invoices,
        "corrections": StockReconciliationLine.corrections,
        "computed_stock": StockReconciliationLine.computed_stock,
        "difference": StockReconciliationLine.difference,
        "status": StockReconciliationLine.status,
    }
    if not params.sort_by:
        query = query.order_by(
            StockReconciliationLine.status.desc(), Product.name
        )
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)

    items = []
    for line, product_name, product_code, product_unit, warehouse_name in result["rows"]:
        out = ReconciliationLineOut.model_validate(line)
        out.product_name = product_name
        out.product_code = product_code
        out.product_unit = product_unit
        out.warehouse_name = warehouse_name
        items.append(out)
    return {**{k: result[k] for k in ("total", "page", "per_page", "pages")}, "items": items}


@router.get("/runs", response_model=Page[ReconciliationRunOut])
def list_runs(
    params: PageParams = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    query = select(ReconciliationRun)
    sortable = {
        "id": ReconciliationRun.id,
        "started_at": ReconciliationRun.started_at,
        "line_count": ReconciliationRun.line_count,
        "discrepancy_count": ReconciliationRun.discrepancy_count,
    }
    if not params.sort_by:
        query = query.order_by(ReconciliationRun.id.desc())
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)
    return {
        **{k: result[k] for k in ("total", "page", "per_page", "pages")},
        "items": [ReconciliationRunOut.model_validate(row[0]) for row in result["rows"]],
    }


@router.get("/summary")
def summary(
    db: Session = Depends(get_db), _: User = Depends(require_any_role)
) -> dict:
    run = ReconciliationService(db).latest_run()
    if run is None:
        return {"run": None}
    return {"run": ReconciliationRunOut.model_validate(run).model_dump()}


@router.post("/refresh", response_model=MessageResponse)
def refresh(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> MessageResponse:
    """Recompute the snapshot from the local mirror (no external API calls)."""
    run = ReconciliationService(db).refresh(user_id=user.id, trigger="MANUAL")
    detail = {
        "run_id": run.id,
        "line_count": run.line_count,
        "discrepancy_count": run.discrepancy_count,
    }
    record_audit(
        db, AuditAction.RECONCILIATION_REFRESHED, user=user, object_type="reconciliation",
        object_id=run.id,
        description=f"Przeliczono tabelę rozliczeniową: {run.line_count} wierszy, "
                    f"{run.discrepancy_count} rozbieżności",
        new_value=detail,
        ip_address=client_ip(request),
    )
    db.commit()
    return MessageResponse(message="Tabela rozliczeniowa przeliczona", detail=detail)


@router.get("/lines/{line_id}", response_model=ReconciliationLineOut)
def get_line(
    line_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> ReconciliationLineOut:
    line = db.get(StockReconciliationLine, line_id)
    if line is None:
        raise HTTPException(status_code=404, detail="Wiersz rozliczenia nie istnieje")
    out = ReconciliationLineOut.model_validate(line)
    product = db.get(Product, line.product_id)
    warehouse = db.get(Warehouse, line.warehouse_id) if line.warehouse_id else None
    out.product_name = product.name if product else None
    out.product_code = product.code if product else None
    out.product_unit = product.unit if product else None
    out.warehouse_name = warehouse.name if warehouse else None
    return out
