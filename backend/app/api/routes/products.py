from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.database.session import get_db
from app.models.enums import AuditAction, ProductKind
from app.models.fakturownia import FakturowniaProduct
from app.models.product import Product, ProductAlias, ProductBundleComponent
from app.models.skyshop import ProductContent
from app.models.stock import LocalStockBalance
from app.models.user import User
from app.models.validation import ValidationIssue
from app.repositories.pagination import PageParams, apply_sort, paginate
from app.schemas.common import MessageResponse, Page
from app.schemas.domain import (
    BundleComponentCreate,
    ProductAliasCreate,
    ProductAliasOut,
    ProductDetailOut,
    ProductOut,
    ProductUpdate,
)
from app.schemas.integrations import ProductContentIn, ProductContentOut
from app.security.auth import client_ip, require_any_role, require_operator
from app.services.parsing import normalize_text
from app.services.report_service import OPEN_ISSUE_STATUSES
from app.services.skyshop_service import SkyShopService, content_hash

router = APIRouter(prefix="/products", tags=["products"])

VALID_KINDS = {k.value for k in ProductKind}


def _stock_subquery():
    return (
        select(
            LocalStockBalance.product_id.label("product_id"),
            func.sum(LocalStockBalance.quantity).label("total_stock"),
        )
        .group_by(LocalStockBalance.product_id)
        .subquery()
    )


@router.get("", response_model=Page[ProductOut])
def list_products(
    params: PageParams = Depends(),
    search: str | None = None,
    kind: str | None = None,
    stock_controlled: bool | None = None,
    active: bool | None = None,
    negative_stock: bool | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    stock = _stock_subquery()
    issues = (
        select(
            ValidationIssue.product_id.label("product_id"),
            func.count(ValidationIssue.id).label("open_issues"),
        )
        .where(ValidationIssue.status.in_(OPEN_ISSUE_STATUSES))
        .group_by(ValidationIssue.product_id)
        .subquery()
    )
    query = (
        select(
            Product,
            stock.c.total_stock,
            FakturowniaProduct.quantity,
            func.coalesce(issues.c.open_issues, 0).label("open_issues"),
        )
        .outerjoin(stock, stock.c.product_id == Product.id)
        .outerjoin(
            FakturowniaProduct,
            FakturowniaProduct.fakturownia_id == Product.fakturownia_product_id,
        )
        .outerjoin(issues, issues.c.product_id == Product.id)
    )
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                Product.name.ilike(pattern),
                Product.code.ilike(pattern),
                Product.ean.ilike(pattern),
                Product.sku.ilike(pattern),
            )
        )
    if kind:
        query = query.where(Product.kind == kind)
    if stock_controlled is not None:
        query = query.where(Product.is_stock_controlled.is_(stock_controlled))
    if active is not None:
        query = query.where(Product.is_active.is_(active))
    if negative_stock:
        query = query.where(func.coalesce(stock.c.total_stock, 0) < 0)

    sortable = {
        "id": Product.id, "name": Product.name, "code": Product.code,
        "kind": Product.kind, "unit": Product.unit,
        "total_local_stock": func.coalesce(stock.c.total_stock, 0),
        "open_issue_count": func.coalesce(issues.c.open_issues, 0),
    }
    if not params.sort_by:
        query = query.order_by(Product.name)
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)

    items = []
    for product, total_stock, fakturownia_qty, open_issues in result["rows"]:
        out = ProductOut.model_validate(product)
        out.total_local_stock = total_stock
        out.fakturownia_quantity = fakturownia_qty
        out.open_issue_count = open_issues
        items.append(out)
    return {**{k: result[k] for k in ("total", "page", "per_page", "pages")}, "items": items}


@router.get("/{product_id}", response_model=ProductDetailOut)
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> ProductDetailOut:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Produkt nie istnieje")
    out = ProductDetailOut.model_validate(product)
    out.total_local_stock = db.execute(
        select(func.coalesce(func.sum(LocalStockBalance.quantity), 0)).where(
            LocalStockBalance.product_id == product_id
        )
    ).scalar_one()
    if product.fakturownia_product_id:
        out.fakturownia_quantity = db.execute(
            select(FakturowniaProduct.quantity).where(
                FakturowniaProduct.fakturownia_id == product.fakturownia_product_id
            )
        ).scalar_one_or_none()
    products_by_id = {
        prod.id: prod.name
        for prod in db.execute(select(Product)).scalars()
    }
    for comp in out.bundle_components:
        comp.component_name = products_by_id.get(comp.component_product_id)
    return out


@router.patch("/{product_id}", response_model=ProductDetailOut)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> ProductDetailOut:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Produkt nie istnieje")
    if payload.kind is not None and payload.kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"Nieznany typ produktu: {payload.kind}")
    old = {
        "kind": product.kind, "is_stock_controlled": product.is_stock_controlled,
        "is_active": product.is_active, "unit": product.unit, "notes": product.notes,
    }
    for field in ("kind", "is_stock_controlled", "is_active", "unit", "notes"):
        value = getattr(payload, field)
        if value is not None:
            setattr(product, field, value)
    record_audit(
        db, AuditAction.UPDATE, user=user, object_type="product", object_id=product.id,
        description=f"Zmieniono lokalną klasyfikację produktu „{product.name}”",
        old_value=old,
        new_value=payload.model_dump(exclude_none=True),
        ip_address=client_ip(request),
    )
    db.commit()
    return get_product(product_id, db, user)


@router.post("/aliases", response_model=ProductAliasOut, status_code=201)
def create_alias(
    payload: ProductAliasCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> ProductAlias:
    product = db.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Produkt nie istnieje")
    normalized = normalize_text(payload.alias_value)
    duplicate = db.execute(
        select(ProductAlias).where(
            ProductAlias.alias_type == payload.alias_type,
            ProductAlias.alias_value_normalized == normalized,
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Taki alias już istnieje")
    alias = ProductAlias(
        product_id=payload.product_id,
        alias_type=payload.alias_type,
        alias_value=payload.alias_value,
        alias_value_normalized=normalized,
        created_by_user_id=user.id,
    )
    db.add(alias)
    db.flush()
    record_audit(
        db, AuditAction.CREATE, user=user, object_type="product_alias", object_id=alias.id,
        description=f"Dodano alias {payload.alias_type}=„{payload.alias_value}” "
                    f"dla produktu „{product.name}”",
        new_value=payload.model_dump(),
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(alias)
    return alias


@router.delete("/aliases/{alias_id}", response_model=MessageResponse)
def delete_alias(
    alias_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> MessageResponse:
    alias = db.get(ProductAlias, alias_id)
    if alias is None:
        raise HTTPException(status_code=404, detail="Alias nie istnieje")
    record_audit(
        db, AuditAction.DELETE, user=user, object_type="product_alias", object_id=alias.id,
        description=f"Usunięto alias {alias.alias_type}=„{alias.alias_value}”",
        old_value={"product_id": alias.product_id, "alias_type": alias.alias_type,
                   "alias_value": alias.alias_value},
        ip_address=client_ip(request),
    )
    db.delete(alias)
    db.commit()
    return MessageResponse(message="Alias usunięty")


@router.put("/{product_id}/bundle", response_model=MessageResponse)
def set_bundle_components(
    product_id: int,
    components: list[BundleComponentCreate],
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> MessageResponse:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Produkt nie istnieje")
    for comp in components:
        if comp.component_product_id == product_id:
            raise HTTPException(status_code=400, detail="Zestaw nie może zawierać samego siebie")
        if db.get(Product, comp.component_product_id) is None:
            raise HTTPException(
                status_code=404, detail=f"Produkt składowy {comp.component_product_id} nie istnieje"
            )
    old = [
        {"component_product_id": c.component_product_id, "quantity": str(c.quantity)}
        for c in product.bundle_components
    ]
    db.execute(
        delete(ProductBundleComponent).where(
            ProductBundleComponent.bundle_product_id == product_id
        )
    )
    for comp in components:
        db.add(
            ProductBundleComponent(
                bundle_product_id=product_id,
                component_product_id=comp.component_product_id,
                quantity=comp.quantity,
            )
        )
    record_audit(
        db, AuditAction.UPDATE, user=user, object_type="product_bundle", object_id=product_id,
        description=f"Zmieniono skład zestawu „{product.name}”",
        old_value={"components": old},
        new_value={"components": [c.model_dump(mode="json") for c in components]},
        ip_address=client_ip(request),
    )
    db.commit()
    return MessageResponse(message="Skład zestawu zapisany lokalnie")


# ------------------------- PIM content (SkyShop) ------------------------ #
@router.get("/{product_id}/content", response_model=ProductContentOut)
def get_product_content(
    product_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> ProductContentOut:
    """Locally curated shop content (description, images, attributes, price)."""
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Produkt nie istnieje")
    content = db.get(ProductContent, product_id)
    out = (
        ProductContentOut.model_validate(content)
        if content is not None
        else ProductContentOut(product_id=product_id)
    )
    out.content_hash = content_hash(product, content)
    out.publication_problems = SkyShopService(db).validate_for_publication(product)
    return out


@router.put("/{product_id}/content", response_model=ProductContentOut)
def save_product_content(
    product_id: int,
    payload: ProductContentIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> ProductContentOut:
    """Save shop content locally. Publication itself goes through the queue."""
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Produkt nie istnieje")
    content = db.get(ProductContent, product_id)
    if content is None:
        content = ProductContent(product_id=product_id, images=[], attributes={})
        db.add(content)
    old_hash = content_hash(product, content)

    # ``exclude_unset`` already separates "not sent" from "sent as null", so an
    # explicit null clears the field instead of being ignored.  The two JSON
    # collections are kept non-null so consumers never have to handle both
    # an empty list and NULL.
    empty_by_field = {"images": [], "attributes": {}}
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is None and field in empty_by_field:
            value = empty_by_field[field]
        setattr(content, field, value)
    if content.is_publishable is None:
        content.is_publishable = True
    content.updated_by_user_id = user.id
    db.flush()

    new_hash = content_hash(product, content)
    record_audit(
        db, AuditAction.UPDATE, user=user, object_type="product_content",
        object_id=product_id,
        description=f"Zapisano dane PIM produktu „{product.name}”",
        old_value={"content_hash": old_hash},
        new_value={"content_hash": new_hash},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(content)
    out = ProductContentOut.model_validate(content)
    out.content_hash = new_hash
    out.publication_problems = SkyShopService(db).validate_for_publication(product)
    return out
