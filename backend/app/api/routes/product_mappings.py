from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.database.session import get_db
from app.models.enums import AuditAction, MappingStatus
from app.models.fakturownia import FakturowniaInvoicePosition
from app.models.product import Product, ProductMapping
from app.models.user import User
from app.repositories.pagination import PageParams, apply_sort, paginate
from app.schemas.common import MessageResponse, Page
from app.schemas.domain import (
    ProductMappingCreate,
    ProductMappingOut,
    ProductMappingUpdate,
)
from app.security.auth import client_ip, require_any_role, require_operator
from app.services.mapping_service import apply_position_mappings
from app.services.parsing import mapping_signature

router = APIRouter(prefix="/product-mappings", tags=["product-mappings"])


def _occurrences_subquery():
    """How many invoice positions share each mapping's source name."""
    return (
        select(
            FakturowniaInvoicePosition.name.label("source_name"),
            func.count(FakturowniaInvoicePosition.id).label("occurrences"),
        )
        .group_by(FakturowniaInvoicePosition.name)
        .subquery()
    )


@router.get("", response_model=Page[ProductMappingOut])
def list_mappings(
    params: PageParams = Depends(),
    status: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    occurrences = _occurrences_subquery()
    query = (
        select(
            ProductMapping,
            Product.name,
            func.coalesce(occurrences.c.occurrences, 0).label("occurrence_count"),
        )
        .outerjoin(Product, Product.id == ProductMapping.product_id)
        .outerjoin(occurrences, occurrences.c.source_name == ProductMapping.source_name)
    )
    if status:
        query = query.where(ProductMapping.status == status)
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                ProductMapping.source_name.ilike(pattern),
                ProductMapping.source_code.ilike(pattern),
                Product.name.ilike(pattern),
            )
        )
    sortable = {
        "id": ProductMapping.id,
        "source_name": ProductMapping.source_name,
        "status": ProductMapping.status,
        "match_type": ProductMapping.match_type,
        "created_at": ProductMapping.created_at,
        "occurrence_count": func.coalesce(occurrences.c.occurrences, 0),
    }
    if not params.sort_by:
        query = query.order_by(ProductMapping.status.desc(), ProductMapping.id.desc())
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)

    items = []
    for mapping, product_name, occurrence_count in result["rows"]:
        out = ProductMappingOut.model_validate(mapping)
        out.product_name = product_name
        out.occurrence_count = occurrence_count
        items.append(out)
    return {**{k: result[k] for k in ("total", "page", "per_page", "pages")}, "items": items}


@router.post("", response_model=ProductMappingOut, status_code=201)
def create_mapping(
    payload: ProductMappingCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> ProductMappingOut:
    """Create a LOCAL product mapping (never propagated to Fakturownia)."""
    product = db.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Produkt nie istnieje")
    if not any([payload.source_name, payload.source_code, payload.source_ean]):
        raise HTTPException(
            status_code=400,
            detail="Podaj co najmniej jedno źródło: nazwę, kod lub EAN",
        )
    signature = mapping_signature(
        payload.source_name, payload.source_code, payload.source_ean, payload.source_unit
    )
    existing = db.execute(
        select(ProductMapping).where(ProductMapping.signature == signature)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Mapowanie dla tej sygnatury już istnieje (id={existing.id})",
        )
    mapping = ProductMapping(
        source_name=payload.source_name,
        source_code=payload.source_code,
        source_ean=payload.source_ean,
        source_unit=payload.source_unit,
        signature=signature,
        product_id=payload.product_id,
        match_type="MANUAL",
        status=str(MappingStatus.CONFIRMED),
        notes=payload.notes,
        created_by_user_id=user.id,
        confirmed_by_user_id=user.id,
    )
    db.add(mapping)
    db.flush()
    apply_position_mappings(db)
    record_audit(
        db, AuditAction.CREATE, user=user, object_type="product_mapping",
        object_id=mapping.id,
        description=f"Utworzono mapowanie „{payload.source_name or payload.source_code}” "
                    f"→ „{product.name}”",
        new_value=payload.model_dump(),
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(mapping)
    out = ProductMappingOut.model_validate(mapping)
    out.product_name = product.name
    return out


@router.patch("/{mapping_id}", response_model=ProductMappingOut)
def update_mapping(
    mapping_id: int,
    payload: ProductMappingUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> ProductMappingOut:
    """Approve / reject / repoint a mapping. Local write only."""
    mapping = db.get(ProductMapping, mapping_id)
    if mapping is None:
        raise HTTPException(status_code=404, detail="Mapowanie nie istnieje")
    old = {
        "product_id": mapping.product_id, "status": mapping.status, "notes": mapping.notes,
    }
    if payload.product_id is not None:
        if db.get(Product, payload.product_id) is None:
            raise HTTPException(status_code=404, detail="Produkt nie istnieje")
        mapping.product_id = payload.product_id
    if payload.status is not None:
        if payload.status == str(MappingStatus.CONFIRMED):
            if mapping.product_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="Nie można zatwierdzić mapowania bez przypisanego produktu",
                )
            from datetime import datetime, timezone

            mapping.confirmed_by_user_id = user.id
            mapping.confirmed_at = datetime.now(timezone.utc)
        mapping.status = payload.status
    if payload.notes is not None:
        mapping.notes = payload.notes
    db.flush()
    # Re-apply mappings so positions pick up the change immediately.
    apply_position_mappings(db)
    record_audit(
        db, AuditAction.UPDATE, user=user, object_type="product_mapping",
        object_id=mapping.id,
        description=f"Zmieniono mapowanie „{mapping.source_name or mapping.source_code}”",
        old_value=old,
        new_value=payload.model_dump(exclude_none=True),
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(mapping)
    out = ProductMappingOut.model_validate(mapping)
    if mapping.product_id:
        product = db.get(Product, mapping.product_id)
        out.product_name = product.name if product else None
    return out


@router.post("/reapply", response_model=MessageResponse)
def reapply_mappings(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> MessageResponse:
    stats = apply_position_mappings(db)
    record_audit(
        db, AuditAction.UPDATE, user=user, object_type="product_mapping",
        description="Ponowne zastosowanie mapowań do pozycji faktur",
        new_value=stats,
        ip_address=client_ip(request),
    )
    db.commit()
    return MessageResponse(message="Mapowania zastosowane ponownie", detail=stats)
