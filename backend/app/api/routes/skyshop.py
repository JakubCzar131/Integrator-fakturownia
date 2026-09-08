"""SkyShop endpoints: product links, mirror, categories, PIM content and queue.

Nothing in this module talks to the shop synchronously except the mirror
refresh (a read).  Every mutation is placed in the ``sync_jobs`` outbox and
executed by the worker, which respects the platform limit of one request per
second, the global kill switch and the dry-run setting.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.database.session import get_db
from app.models.enums import (
    AuditAction,
    SkyShopLinkStatus,
    SyncJobStatus,
    SyncJobType,
)
from app.models.product import Product
from app.models.skyshop import (
    ProductContent,
    SkyShopCategory,
    SkyShopCategoryMapping,
    SkyShopProduct,
    SkyShopProductLink,
)
from app.models.sync import SyncJob
from app.models.user import User
from app.repositories.pagination import PageParams, apply_sort, paginate
from app.schemas.common import MessageResponse, Page
from app.schemas.integrations import (
    ProductContentIn,
    ProductContentOut,
    ProductPushRequest,
    SkyShopCategoryMappingIn,
    SkyShopCategoryMappingOut,
    SkyShopCategoryOut,
    SkyShopLinkOut,
    SkyShopLinkUpdate,
    SkyShopProductOut,
    StockSyncRequest,
    SyncJobOut,
)
from app.security.auth import client_ip, require_any_role, require_operator
from app.services.skyshop_client import SkyShopError, SkyShopNotConfigured
from app.services.skyshop_service import SkyShopService, content_hash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/skyshop", tags=["skyshop"])


# ------------------------------ overview -------------------------------- #
@router.get("/summary")
def summary(db: Session = Depends(get_db), _: User = Depends(require_any_role)) -> dict:
    return SkyShopService(db).summary()


# ------------------------------- links ---------------------------------- #
@router.get("/links", response_model=Page[SkyShopLinkOut])
def list_links(
    params: PageParams = Depends(),
    search: str | None = None,
    status: str | None = None,
    only_out_of_sync: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    query = select(SkyShopProductLink, Product).join(
        Product, Product.id == SkyShopProductLink.product_id
    )
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                Product.name.ilike(pattern),
                Product.code.ilike(pattern),
                Product.sku.ilike(pattern),
                Product.ean.ilike(pattern),
            )
        )
    if status:
        query = query.where(SkyShopProductLink.status == status)

    sortable = {
        "product_name": Product.name,
        "status": SkyShopProductLink.status,
        "last_pushed_at": SkyShopProductLink.last_pushed_at,
        "last_pushed_stock": SkyShopProductLink.last_pushed_stock,
    }
    if not params.sort_by:
        query = query.order_by(SkyShopProductLink.status, Product.name)
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)

    service = SkyShopService(db)
    stock = service.stock_map()
    shop_products = {
        row.skyshop_id: row
        for row in db.execute(select(SkyShopProduct)).scalars()
    }

    items = []
    for link, product in result["rows"]:
        out = SkyShopLinkOut.model_validate(link)
        out.product_name = product.name
        out.product_code = product.code
        out.product_sku = product.sku
        out.product_ean = product.ean
        local_stock = stock.get(product.id)
        out.local_stock = local_stock
        mirror = shop_products.get(link.skyshop_id) if link.skyshop_id else None
        out.shop_stock = mirror.quantity if mirror else None
        out.shop_name = mirror.name if mirror else None
        out.stock_out_of_sync = bool(
            link.status == str(SkyShopLinkStatus.LINKED)
            and local_stock is not None
            and (link.last_pushed_stock is None or link.last_pushed_stock != local_stock)
        )
        out.content_out_of_sync = bool(
            link.last_pushed_content_hash
            != content_hash(product, db.get(ProductContent, product.id))
        )
        items.append(out)
    if only_out_of_sync:
        items = [item for item in items if item.stock_out_of_sync or item.content_out_of_sync]
    return {**{k: result[k] for k in ("total", "page", "per_page", "pages")}, "items": items}


@router.post("/links/match", response_model=MessageResponse)
def match_links(
    request: Request,
    only_unlinked: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> MessageResponse:
    """Match local products against the mirror by SKU, then EAN (no API calls)."""
    stats = SkyShopService(db).match_links(only_unlinked=only_unlinked)
    record_audit(
        db, AuditAction.UPDATE, user=user, object_type="skyshop_links",
        description="Uruchomiono automatyczne dopasowanie produktów do SkyShop",
        new_value=stats, ip_address=client_ip(request),
    )
    db.commit()
    return MessageResponse(message="Dopasowanie zakończone", detail=stats)


@router.patch("/links/{product_id}", response_model=SkyShopLinkOut)
def update_link(
    product_id: int,
    payload: SkyShopLinkUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> SkyShopLinkOut:
    """Manual decision: link to a shop product, or exclude the product."""
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Produkt nie istnieje")
    service = SkyShopService(db)
    link = service.ensure_link(product_id)
    old = {"skyshop_id": link.skyshop_id, "status": link.status}

    if payload.skyshop_id is not None:
        link.skyshop_id = payload.skyshop_id or None
        link.match_type = "MANUAL"
        link.candidate_skyshop_ids = None
        link.status = str(
            SkyShopLinkStatus.LINKED if payload.skyshop_id else SkyShopLinkStatus.MISSING
        )
    if payload.status is not None:
        link.status = payload.status
    if payload.notes is not None:
        link.notes = payload.notes
    link.updated_by_user_id = user.id

    record_audit(
        db, AuditAction.UPDATE, user=user, object_type="skyshop_product_link",
        object_id=product_id,
        description=f"Zmieniono powiązanie SkyShop dla „{product.name}”",
        old_value=old,
        new_value={"skyshop_id": link.skyshop_id, "status": link.status},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(link)
    out = SkyShopLinkOut.model_validate(link)
    out.product_name = product.name
    return out


# ------------------------------- mirror --------------------------------- #
@router.get("/products", response_model=Page[SkyShopProductOut])
def list_mirror_products(
    params: PageParams = Depends(),
    search: str | None = None,
    only_unlinked: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    query = select(SkyShopProduct)
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(SkyShopProduct.name.ilike(pattern), SkyShopProduct.sku.ilike(pattern),
                SkyShopProduct.ean.ilike(pattern))
        )
    if only_unlinked:
        linked = select(SkyShopProductLink.skyshop_id).where(
            SkyShopProductLink.skyshop_id.isnot(None)
        )
        query = query.where(SkyShopProduct.skyshop_id.notin_(linked))
    sortable = {
        "name": SkyShopProduct.name,
        "sku": SkyShopProduct.sku,
        "quantity": SkyShopProduct.quantity,
        "price_gross": SkyShopProduct.price_gross,
        "last_synced_at": SkyShopProduct.last_synced_at,
    }
    if not params.sort_by:
        query = query.order_by(SkyShopProduct.name)
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)
    return {
        **{k: result[k] for k in ("total", "page", "per_page", "pages")},
        "items": [SkyShopProductOut.model_validate(row[0]) for row in result["rows"]],
    }


@router.post("/mirror/refresh", response_model=MessageResponse)
def refresh_mirror(
    request: Request,
    background: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> MessageResponse:
    """Refresh the local copy of the shop catalogue (read-only operation).

    ``background=true`` queues the refresh instead of blocking the request —
    useful for large catalogues, since reads are rate-limited too.
    """
    service = SkyShopService(db)
    if background:
        job = service.enqueue_job(
            SyncJobType.SKYSHOP_MIRROR_REFRESH,
            payload={},
            dedupe_key="mirror:refresh",
            priority=8,
            user_id=user.id,
        )
        db.commit()
        return MessageResponse(
            message="Odświeżenie mirroru dodane do kolejki", detail={"job_id": job.id}
        )
    try:
        stats = service.refresh_mirror()
    except SkyShopNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SkyShopError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    finally:
        service.close()
    record_audit(
        db, AuditAction.UPDATE, user=user, object_type="skyshop_mirror",
        description="Odświeżono mirror produktów i kategorii SkyShop",
        new_value=stats, ip_address=client_ip(request),
    )
    db.commit()
    return MessageResponse(message="Mirror SkyShop odświeżony", detail=stats)


# ----------------------------- categories -------------------------------- #
@router.get("/categories", response_model=list[SkyShopCategoryOut])
def list_categories(
    db: Session = Depends(get_db), _: User = Depends(require_any_role)
) -> list[SkyShopCategoryOut]:
    mappings = {
        mapping.skyshop_category_id: mapping.local_category
        for mapping in db.execute(select(SkyShopCategoryMapping)).scalars()
    }
    result = []
    for category in db.execute(
        select(SkyShopCategory).order_by(SkyShopCategory.name)
    ).scalars():
        out = SkyShopCategoryOut.model_validate(category)
        out.mapped_local_category = mappings.get(category.skyshop_id)
        result.append(out)
    return result


@router.get("/category-mappings", response_model=list[SkyShopCategoryMappingOut])
def list_category_mappings(
    db: Session = Depends(get_db), _: User = Depends(require_any_role)
) -> list[SkyShopCategoryMappingOut]:
    names = {
        category.skyshop_id: category.name
        for category in db.execute(select(SkyShopCategory)).scalars()
    }
    result = []
    for mapping in db.execute(
        select(SkyShopCategoryMapping).order_by(SkyShopCategoryMapping.local_category)
    ).scalars():
        out = SkyShopCategoryMappingOut.model_validate(mapping)
        out.skyshop_category_name = names.get(mapping.skyshop_category_id)
        result.append(out)
    return result


@router.put("/category-mappings", response_model=SkyShopCategoryMappingOut)
def upsert_category_mapping(
    payload: SkyShopCategoryMappingIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> SkyShopCategoryMappingOut:
    mapping = db.execute(
        select(SkyShopCategoryMapping).where(
            SkyShopCategoryMapping.local_category == payload.local_category
        )
    ).scalar_one_or_none()
    if mapping is None:
        mapping = SkyShopCategoryMapping(local_category=payload.local_category)
        db.add(mapping)
    mapping.skyshop_category_id = payload.skyshop_category_id
    mapping.created_by_user_id = mapping.created_by_user_id or user.id
    record_audit(
        db, AuditAction.UPDATE, user=user, object_type="skyshop_category_mapping",
        object_id=payload.local_category,
        description=f"Zmapowano kategorię „{payload.local_category}” na "
                    f"kategorię SkyShop {payload.skyshop_category_id}",
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(mapping)
    return SkyShopCategoryMappingOut.model_validate(mapping)


@router.delete("/category-mappings/{mapping_id}", response_model=MessageResponse)
def delete_category_mapping(
    mapping_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> MessageResponse:
    mapping = db.get(SkyShopCategoryMapping, mapping_id)
    if mapping is None:
        raise HTTPException(status_code=404, detail="Mapowanie kategorii nie istnieje")
    record_audit(
        db, AuditAction.DELETE, user=user, object_type="skyshop_category_mapping",
        object_id=mapping.local_category,
        description=f"Usunięto mapowanie kategorii „{mapping.local_category}”",
        ip_address=client_ip(request),
    )
    db.delete(mapping)
    db.commit()
    return MessageResponse(message="Mapowanie kategorii usunięte")


# ---------------------------- publications ------------------------------- #
@router.post("/products/push", response_model=MessageResponse)
def push_products(
    payload: ProductPushRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> MessageResponse:
    """Queue publication (create/update) of the selected products."""
    service = SkyShopService(db)
    stats = service.enqueue_product_push(
        payload.product_ids, mode=payload.mode, user_id=user.id, force=payload.force
    )
    record_audit(
        db, AuditAction.JOB_ENQUEUED, user=user, object_type="skyshop_products",
        description=f"Zakolejkowano publikację {stats['enqueued']} produktów do SkyShop",
        new_value=stats, ip_address=client_ip(request),
    )
    db.commit()
    return MessageResponse(
        message=f"Zakolejkowano {stats['enqueued']} produktów", detail=stats
    )


@router.post("/stock/sync", response_model=MessageResponse)
def sync_stock(
    payload: StockSyncRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> MessageResponse:
    """Queue a stock push for products whose quantity differs from the last push."""
    stats = SkyShopService(db).enqueue_stock_sync(
        user_id=user.id, product_ids=payload.product_ids, force=payload.force
    )
    record_audit(
        db, AuditAction.JOB_ENQUEUED, user=user, object_type="skyshop_stock",
        description=f"Zakolejkowano aktualizację stanów dla {stats['enqueued']} produktów",
        new_value=stats, ip_address=client_ip(request),
    )
    db.commit()
    return MessageResponse(
        message=f"Zakolejkowano {stats['enqueued']} aktualizacji stanów", detail=stats
    )


# ------------------------------- queue ---------------------------------- #
@router.get("/jobs", response_model=Page[SyncJobOut])
def list_jobs(
    params: PageParams = Depends(),
    status: str | None = None,
    job_type: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    query = select(SyncJob, Product.name).outerjoin(Product, Product.id == SyncJob.product_id)
    if status:
        query = query.where(SyncJob.status == status)
    if job_type:
        query = query.where(SyncJob.job_type == job_type)
    sortable = {
        "id": SyncJob.id,
        "status": SyncJob.status,
        "job_type": SyncJob.job_type,
        "created_at": SyncJob.created_at,
        "next_attempt_at": SyncJob.next_attempt_at,
        "priority": SyncJob.priority,
    }
    if not params.sort_by:
        query = query.order_by(SyncJob.id.desc())
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)
    items = []
    for job, product_name in result["rows"]:
        out = SyncJobOut.model_validate(job)
        out.product_name = product_name
        items.append(out)
    return {**{k: result[k] for k in ("total", "page", "per_page", "pages")}, "items": items}


@router.post("/jobs/{job_id}/retry", response_model=MessageResponse)
def retry_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> MessageResponse:
    """Return a dead-lettered job to the queue with a fresh attempt budget."""
    job = db.get(SyncJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Zadanie nie istnieje")
    if job.status == str(SyncJobStatus.RUNNING):
        raise HTTPException(status_code=409, detail="Zadanie jest właśnie wykonywane")
    job.status = str(SyncJobStatus.PENDING)
    job.attempts = 0
    job.last_error = None
    job.finished_at = None
    job.next_attempt_at = func.now()
    db.commit()
    return MessageResponse(message=f"Zadanie #{job_id} wróciło do kolejki")


@router.post("/jobs/{job_id}/cancel", response_model=MessageResponse)
def cancel_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> MessageResponse:
    job = db.get(SyncJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Zadanie nie istnieje")
    if job.status in (str(SyncJobStatus.SUCCESS), str(SyncJobStatus.RUNNING)):
        raise HTTPException(
            status_code=409, detail="Nie można anulować zadania w tym stanie"
        )
    job.status = str(SyncJobStatus.CANCELLED)
    job.finished_at = func.now()
    db.commit()
    return MessageResponse(message=f"Zadanie #{job_id} anulowane")


@router.post("/jobs/process", response_model=MessageResponse)
def process_jobs(
    limit: int = 5,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> MessageResponse:
    """Run one worker pass now (the scheduler does this automatically)."""
    from app.services.sync_worker import process_pending_jobs

    stats = process_pending_jobs(db, limit=limit)
    return MessageResponse(message="Kolejka przetworzona", detail=stats)
