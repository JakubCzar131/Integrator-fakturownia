"""Warehouse documents downloaded from Fakturownia (PZ, PW, WZ, RW, MM).

Documents and their positions are mirrored read-only; nothing here writes
towards Fakturownia.  ``POST /warehouse-documents/rebuild-positions``
re-normalizes positions out of the stored payloads and re-runs the product
mapping — useful after confirming new mappings without waiting for a sync.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.database.session import get_db
from app.models.enums import AuditAction, WarehouseDocumentKind
from app.models.fakturownia import (
    Warehouse,
    WarehouseDocument,
    WarehouseDocumentPosition,
)
from app.models.product import Product
from app.models.user import User
from app.repositories.pagination import PageParams, apply_sort, paginate
from app.schemas.common import MessageResponse, Page
from app.schemas.integrations import (
    WarehouseDocumentDetailOut,
    WarehouseDocumentOut,
    WarehouseDocumentPositionOut,
)
from app.security.auth import client_ip, require_any_role, require_operator
from app.services.mapping_service import apply_document_position_mappings
from app.services.warehouse_document_service import rebuild_document_positions

router = APIRouter(prefix="/warehouse-documents", tags=["warehouse-documents"])

INBOUND_KINDS = [str(WarehouseDocumentKind.PZ), str(WarehouseDocumentKind.PW)]


@router.get("", response_model=Page[WarehouseDocumentOut])
def list_documents(
    params: PageParams = Depends(),
    search: str | None = None,
    kind: str | None = None,
    only_inbound: bool = False,
    warehouse_fakturownia_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    query = select(WarehouseDocument, Warehouse.name).outerjoin(
        Warehouse, Warehouse.fakturownia_id == WarehouseDocument.warehouse_fakturownia_id
    )
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(WarehouseDocument.number.ilike(pattern),
                WarehouseDocument.description.ilike(pattern))
        )
    if kind:
        query = query.where(WarehouseDocument.kind == kind)
    if only_inbound:
        # Goods receipts: the documents that put stock on the shelf.
        query = query.where(
            func.upper(WarehouseDocument.kind).in_(INBOUND_KINDS)
        )
    if warehouse_fakturownia_id:
        query = query.where(
            WarehouseDocument.warehouse_fakturownia_id == warehouse_fakturownia_id
        )
    if date_from:
        query = query.where(WarehouseDocument.issue_date >= date_from)
    if date_to:
        query = query.where(WarehouseDocument.issue_date <= date_to)

    sortable = {
        "issue_date": WarehouseDocument.issue_date,
        "number": WarehouseDocument.number,
        "kind": WarehouseDocument.kind,
        "id": WarehouseDocument.id,
    }
    if not params.sort_by:
        query = query.order_by(WarehouseDocument.issue_date.desc(), WarehouseDocument.id.desc())
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)

    document_ids = [row[0].id for row in result["rows"]]
    aggregates: dict[int, tuple[int, object]] = {}
    unmapped_counts: dict[int, int] = {}
    if document_ids:
        aggregates = {
            document_id: (count, total)
            for document_id, count, total in db.execute(
                select(
                    WarehouseDocumentPosition.document_id,
                    func.count(WarehouseDocumentPosition.id),
                    func.sum(WarehouseDocumentPosition.quantity),
                )
                .where(WarehouseDocumentPosition.document_id.in_(document_ids))
                .group_by(WarehouseDocumentPosition.document_id)
            ).all()
        }
        unmapped_counts = dict(
            db.execute(
                select(
                    WarehouseDocumentPosition.document_id,
                    func.count(WarehouseDocumentPosition.id),
                )
                .where(
                    WarehouseDocumentPosition.document_id.in_(document_ids),
                    WarehouseDocumentPosition.mapped_product_id.is_(None),
                )
                .group_by(WarehouseDocumentPosition.document_id)
            ).all()
        )

    items = []
    for document, warehouse_name in result["rows"]:
        out = WarehouseDocumentOut.model_validate(document)
        out.warehouse_name = warehouse_name
        count, total = aggregates.get(document.id, (0, None))
        out.position_count = count
        out.total_quantity = total
        out.unmapped_position_count = unmapped_counts.get(document.id, 0)
        items.append(out)
    return {**{k: result[k] for k in ("total", "page", "per_page", "pages")}, "items": items}


@router.get("/positions", response_model=Page[WarehouseDocumentPositionOut])
def list_positions(
    params: PageParams = Depends(),
    search: str | None = None,
    document_kind: str | None = None,
    only_inbound: bool = False,
    product_id: int | None = None,
    only_unmapped: bool = False,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    query = (
        select(WarehouseDocumentPosition, Product.name, WarehouseDocument.number)
        .join(
            WarehouseDocument,
            WarehouseDocument.id == WarehouseDocumentPosition.document_id,
        )
        .outerjoin(Product, Product.id == WarehouseDocumentPosition.mapped_product_id)
    )
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(WarehouseDocumentPosition.name.ilike(pattern),
                WarehouseDocumentPosition.code.ilike(pattern))
        )
    if document_kind:
        query = query.where(WarehouseDocumentPosition.document_kind == document_kind)
    if only_inbound:
        query = query.where(WarehouseDocumentPosition.document_kind.in_(INBOUND_KINDS))
    if product_id:
        query = query.where(WarehouseDocumentPosition.mapped_product_id == product_id)
    if only_unmapped:
        query = query.where(WarehouseDocumentPosition.mapped_product_id.is_(None))
    if date_from:
        query = query.where(WarehouseDocumentPosition.issue_date >= date_from)
    if date_to:
        query = query.where(WarehouseDocumentPosition.issue_date <= date_to)

    sortable = {
        "issue_date": WarehouseDocumentPosition.issue_date,
        "quantity": WarehouseDocumentPosition.quantity,
        "name": WarehouseDocumentPosition.name,
        "document_kind": WarehouseDocumentPosition.document_kind,
        "purchase_price_net": WarehouseDocumentPosition.purchase_price_net,
    }
    if not params.sort_by:
        query = query.order_by(
            WarehouseDocumentPosition.issue_date.desc(), WarehouseDocumentPosition.id.desc()
        )
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)

    items = []
    for position, product_name, document_number in result["rows"]:
        out = WarehouseDocumentPositionOut.model_validate(position)
        out.product_name = product_name
        out.document_number = document_number
        items.append(out)
    return {**{k: result[k] for k in ("total", "page", "per_page", "pages")}, "items": items}


@router.get("/summary")
def summary(db: Session = Depends(get_db), _: User = Depends(require_any_role)) -> dict:
    """Per-kind counts plus how many receipt positions still lack a mapping."""
    by_kind = [
        {"kind": kind or "—", "documents": count}
        for kind, count in db.execute(
            select(WarehouseDocument.kind, func.count(WarehouseDocument.id))
            .where(WarehouseDocument.is_deleted_upstream.is_(False))
            .group_by(WarehouseDocument.kind)
        ).all()
    ]
    inbound_positions = db.execute(
        select(func.count(WarehouseDocumentPosition.id)).where(
            WarehouseDocumentPosition.document_kind.in_(INBOUND_KINDS)
        )
    ).scalar_one()
    unmapped = db.execute(
        select(func.count(WarehouseDocumentPosition.id)).where(
            WarehouseDocumentPosition.document_kind.in_(INBOUND_KINDS),
            WarehouseDocumentPosition.mapped_product_id.is_(None),
        )
    ).scalar_one()
    inbound_quantity = db.execute(
        select(func.sum(WarehouseDocumentPosition.quantity)).where(
            WarehouseDocumentPosition.document_kind.in_(INBOUND_KINDS)
        )
    ).scalar_one()
    return {
        "by_kind": by_kind,
        "inbound_position_count": inbound_positions,
        "inbound_unmapped_count": unmapped,
        "inbound_quantity": str(inbound_quantity) if inbound_quantity is not None else "0",
    }


@router.post("/rebuild-positions", response_model=MessageResponse)
def rebuild_positions(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> MessageResponse:
    """Re-normalize positions from stored payloads and re-run product mapping."""
    stats = rebuild_document_positions(db)
    stats["mapping"] = apply_document_position_mappings(db)
    record_audit(
        db, AuditAction.UPDATE, user=user, object_type="warehouse_document_positions",
        description="Przebudowano pozycje dokumentów magazynowych z zapisanych payloadów",
        new_value=stats,
        ip_address=client_ip(request),
    )
    db.commit()
    return MessageResponse(message="Pozycje dokumentów przebudowane", detail=stats)


@router.get("/{document_id}", response_model=WarehouseDocumentDetailOut)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> WarehouseDocumentDetailOut:
    document = db.get(WarehouseDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokument magazynowy nie istnieje")
    warehouse = db.execute(
        select(Warehouse).where(
            Warehouse.fakturownia_id == document.warehouse_fakturownia_id
        )
    ).scalars().first()
    product_names = dict(
        db.execute(select(Product.id, Product.name)).all()
    )
    out = WarehouseDocumentDetailOut.model_validate(document)
    out.warehouse_name = warehouse.name if warehouse else None
    out.position_count = len(document.positions)
    out.total_quantity = sum(
        (position.quantity or 0) for position in document.positions
    ) or None
    out.unmapped_position_count = sum(
        1 for position in document.positions if position.mapped_product_id is None
    )
    positions = []
    for position in document.positions:
        item = WarehouseDocumentPositionOut.model_validate(position)
        item.product_name = product_names.get(position.mapped_product_id)
        item.document_number = document.number
        positions.append(item)
    out.positions = positions
    return out
