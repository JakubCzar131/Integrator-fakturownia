from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.audit.service import record_audit
from app.database.session import get_db
from app.models.enums import AuditAction
from app.models.fakturownia import (
    FakturowniaInvoice,
    FakturowniaProduct,
    FakturowniaProductStock,
    Warehouse,
)
from app.models.product import Product
from app.models.stock import (
    LocalStockAdjustment,
    LocalStockBalance,
    LocalStockLedgerEntry,
    OpeningBalance,
)
from app.models.user import User
from app.repositories.pagination import PageParams, apply_sort, paginate
from app.schemas.common import MessageResponse, Page
from app.schemas.domain import (
    OpeningBalanceCreate,
    OpeningBalanceOut,
    StockAdjustmentCreate,
    StockAdjustmentOut,
    StockBalanceOut,
    StockLedgerEntryOut,
    WarehouseOut,
)
from app.security.auth import client_ip, require_any_role, require_operator
from app.services.stock_service import StockService

router = APIRouter(tags=["stock"])


# --------------------------- warehouses -------------------------------- #
@router.get("/warehouses", response_model=list[WarehouseOut])
def list_warehouses(
    db: Session = Depends(get_db), _: User = Depends(require_any_role)
) -> list[WarehouseOut]:
    warehouses = db.execute(select(Warehouse).order_by(Warehouse.id)).scalars().all()
    counts = dict(
        db.execute(
            select(LocalStockBalance.warehouse_id, func.count(LocalStockBalance.id))
            .group_by(LocalStockBalance.warehouse_id)
        ).all()
    )
    negatives = dict(
        db.execute(
            select(LocalStockBalance.warehouse_id, func.count(LocalStockBalance.id))
            .where(LocalStockBalance.quantity < 0)
            .group_by(LocalStockBalance.warehouse_id)
        ).all()
    )
    result = []
    for warehouse in warehouses:
        out = WarehouseOut.model_validate(warehouse)
        out.product_count = counts.get(warehouse.id, 0)
        out.negative_count = negatives.get(warehouse.id, 0)
        result.append(out)
    return result


# ---------------------------- balances --------------------------------- #
@router.get("/stock/balances", response_model=Page[StockBalanceOut])
def list_balances(
    params: PageParams = Depends(),
    search: str | None = None,
    warehouse_id: int | None = None,
    product_id: int | None = None,
    only_negative: bool = False,
    only_discrepancies: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    query = (
        select(
            LocalStockBalance,
            Product.name,
            Product.code,
            Product.unit,
            Product.fakturownia_product_id,
            Warehouse.name,
            Warehouse.fakturownia_id,
        )
        .join(Product, Product.id == LocalStockBalance.product_id)
        .join(Warehouse, Warehouse.id == LocalStockBalance.warehouse_id)
    )
    if search:
        pattern = f"%{search}%"
        query = query.where(or_(Product.name.ilike(pattern), Product.code.ilike(pattern)))
    if warehouse_id:
        query = query.where(LocalStockBalance.warehouse_id == warehouse_id)
    if product_id:
        query = query.where(LocalStockBalance.product_id == product_id)
    if only_negative:
        query = query.where(LocalStockBalance.quantity < 0)

    sortable = {
        "quantity": LocalStockBalance.quantity,
        "product_name": Product.name,
        "warehouse_name": Warehouse.name,
        "last_movement_at": LocalStockBalance.last_movement_at,
        "last_sale_at": LocalStockBalance.last_sale_at,
    }
    if not params.sort_by:
        query = query.order_by(Product.name)
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)

    remote_stock = {
        (row.product_fakturownia_id, row.warehouse_fakturownia_id): row.quantity
        for row in db.execute(select(FakturowniaProductStock)).scalars()
        if row.quantity is not None
    }
    remote_global = {
        fp.fakturownia_id: fp.quantity
        for fp in db.execute(select(FakturowniaProduct)).scalars()
        if fp.quantity is not None
    }

    items = []
    for balance, product_name, product_code, product_unit, product_fid, wh_name, wh_fid in result["rows"]:
        out = StockBalanceOut.model_validate(balance)
        out.product_name = product_name
        out.product_code = product_code
        out.product_unit = product_unit
        out.warehouse_name = wh_name
        remote_qty = None
        if product_fid is not None:
            if wh_fid is not None:
                remote_qty = remote_stock.get((product_fid, wh_fid))
            if remote_qty is None:
                remote_qty = remote_global.get(product_fid)
        out.fakturownia_quantity = remote_qty
        out.difference = (balance.quantity - remote_qty) if remote_qty is not None else None
        items.append(out)
    if only_discrepancies:
        items = [i for i in items if i.difference not in (None, 0)]
    return {**{k: result[k] for k in ("total", "page", "per_page", "pages")}, "items": items}


# ----------------------------- ledger ----------------------------------- #
@router.get("/stock/ledger", response_model=Page[StockLedgerEntryOut])
def list_ledger(
    params: PageParams = Depends(),
    product_id: int | None = None,
    warehouse_id: int | None = None,
    movement_type: str | None = None,
    invoice_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    invoice = aliased(FakturowniaInvoice)
    query = (
        select(
            LocalStockLedgerEntry,
            Product.name,
            Warehouse.name,
            invoice.number,
        )
        .join(Product, Product.id == LocalStockLedgerEntry.product_id)
        .join(Warehouse, Warehouse.id == LocalStockLedgerEntry.warehouse_id)
        .outerjoin(invoice, invoice.id == LocalStockLedgerEntry.source_invoice_id)
    )
    if product_id:
        query = query.where(LocalStockLedgerEntry.product_id == product_id)
    if warehouse_id:
        query = query.where(LocalStockLedgerEntry.warehouse_id == warehouse_id)
    if movement_type:
        query = query.where(LocalStockLedgerEntry.movement_type == movement_type)
    if invoice_id:
        query = query.where(LocalStockLedgerEntry.source_invoice_id == invoice_id)

    sortable = {
        "occurred_at": LocalStockLedgerEntry.occurred_at,
        "sequence": LocalStockLedgerEntry.sequence,
        "movement_type": LocalStockLedgerEntry.movement_type,
        "quantity_change": LocalStockLedgerEntry.quantity_change,
        "balance_after": LocalStockLedgerEntry.balance_after,
        "product_name": Product.name,
    }
    if not params.sort_by:
        query = query.order_by(LocalStockLedgerEntry.sequence.desc())
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)

    items = []
    for entry, product_name, warehouse_name, invoice_number in result["rows"]:
        out = StockLedgerEntryOut.model_validate(entry)
        out.product_name = product_name
        out.warehouse_name = warehouse_name
        out.invoice_number = invoice_number
        items.append(out)
    return {**{k: result[k] for k in ("total", "page", "per_page", "pages")}, "items": items}


# ------------------------ opening balances ------------------------------ #
@router.get("/stock/opening-balances", response_model=Page[OpeningBalanceOut])
def list_opening_balances(
    params: PageParams = Depends(),
    product_id: int | None = None,
    warehouse_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    query = (
        select(OpeningBalance, Product.name, Warehouse.name)
        .join(Product, Product.id == OpeningBalance.product_id)
        .join(Warehouse, Warehouse.id == OpeningBalance.warehouse_id)
    )
    if product_id:
        query = query.where(OpeningBalance.product_id == product_id)
    if warehouse_id:
        query = query.where(OpeningBalance.warehouse_id == warehouse_id)
    sortable = {
        "as_of_date": OpeningBalance.as_of_date,
        "quantity": OpeningBalance.quantity,
        "product_name": Product.name,
    }
    if not params.sort_by:
        query = query.order_by(OpeningBalance.id.desc())
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)
    items = []
    for balance, product_name, warehouse_name in result["rows"]:
        out = OpeningBalanceOut.model_validate(balance)
        out.product_name = product_name
        out.warehouse_name = warehouse_name
        items.append(out)
    return {**{k: result[k] for k in ("total", "page", "per_page", "pages")}, "items": items}


@router.post("/stock/opening-balances", response_model=OpeningBalanceOut, status_code=201)
def set_opening_balance(
    payload: OpeningBalanceCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> OpeningBalanceOut:
    """Set the LOCAL opening balance for a product in a warehouse."""
    product = db.get(Product, payload.product_id)
    warehouse = db.get(Warehouse, payload.warehouse_id)
    if product is None or warehouse is None:
        raise HTTPException(status_code=404, detail="Produkt lub magazyn nie istnieje")
    service = StockService(db)
    balance = service.set_opening_balance(
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        as_of_date=payload.as_of_date,
        note=payload.note,
        user_id=user.id,
    )
    record_audit(
        db, AuditAction.CREATE, user=user, object_type="opening_balance",
        object_id=balance.id,
        description=f"Ustawiono stan początkowy „{product.name}” w magazynie "
                    f"„{warehouse.name}”: {payload.quantity}",
        new_value=payload.model_dump(mode="json"),
        ip_address=client_ip(request),
    )
    service.rebuild_stock(user_id=user.id)
    db.commit()
    db.refresh(balance)
    out = OpeningBalanceOut.model_validate(balance)
    out.product_name = product.name
    out.warehouse_name = warehouse.name
    return out


# ---------------------- local adjustments ------------------------------- #
@router.get("/stock/local-adjustments", response_model=Page[StockAdjustmentOut])
def list_adjustments(
    params: PageParams = Depends(),
    product_id: int | None = None,
    warehouse_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    query = (
        select(LocalStockAdjustment, Product.name, Warehouse.name)
        .join(Product, Product.id == LocalStockAdjustment.product_id)
        .join(Warehouse, Warehouse.id == LocalStockAdjustment.warehouse_id)
    )
    if product_id:
        query = query.where(LocalStockAdjustment.product_id == product_id)
    if warehouse_id:
        query = query.where(LocalStockAdjustment.warehouse_id == warehouse_id)
    sortable = {
        "occurred_at": LocalStockAdjustment.occurred_at,
        "quantity_change": LocalStockAdjustment.quantity_change,
        "product_name": Product.name,
    }
    if not params.sort_by:
        query = query.order_by(LocalStockAdjustment.id.desc())
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)
    items = []
    for adjustment, product_name, warehouse_name in result["rows"]:
        out = StockAdjustmentOut.model_validate(adjustment)
        out.product_name = product_name
        out.warehouse_name = warehouse_name
        items.append(out)
    return {**{k: result[k] for k in ("total", "page", "per_page", "pages")}, "items": items}


@router.post("/stock/local-adjustments", response_model=StockAdjustmentOut, status_code=201)
def create_adjustment(
    payload: StockAdjustmentCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> StockAdjustmentOut:
    """Create a LOCAL stock adjustment (never touches Fakturownia)."""
    product = db.get(Product, payload.product_id)
    warehouse = db.get(Warehouse, payload.warehouse_id)
    if product is None or warehouse is None:
        raise HTTPException(status_code=404, detail="Produkt lub magazyn nie istnieje")
    service = StockService(db)
    adjustment = service.create_adjustment(
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        quantity_change=payload.quantity_change,
        description=payload.description,
        occurred_at=payload.occurred_at,
        user_id=user.id,
    )
    record_audit(
        db, AuditAction.CREATE, user=user, object_type="stock_adjustment",
        object_id=adjustment.id,
        description=f"Korekta lokalna „{product.name}” w „{warehouse.name}”: "
                    f"{payload.quantity_change} ({payload.description})",
        new_value=payload.model_dump(mode="json"),
        ip_address=client_ip(request),
    )
    service.rebuild_stock(user_id=user.id)
    db.commit()
    db.refresh(adjustment)
    out = StockAdjustmentOut.model_validate(adjustment)
    out.product_name = product.name
    out.warehouse_name = warehouse.name
    return out


@router.post("/stock/local-adjustments/{adjustment_id}/reverse",
             response_model=StockAdjustmentOut, status_code=201)
def reverse_adjustment(
    adjustment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> StockAdjustmentOut:
    """Reverse an adjustment with a compensating entry (history is never deleted)."""
    service = StockService(db)
    try:
        reversal = service.reverse_adjustment(adjustment_id, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    record_audit(
        db, AuditAction.CREATE, user=user, object_type="stock_adjustment",
        object_id=reversal.id,
        description=f"Storno korekty #{adjustment_id}",
        new_value={"reverses_adjustment_id": adjustment_id,
                   "quantity_change": str(reversal.quantity_change)},
        ip_address=client_ip(request),
    )
    service.rebuild_stock(user_id=user.id)
    db.commit()
    db.refresh(reversal)
    out = StockAdjustmentOut.model_validate(reversal)
    product = db.get(Product, reversal.product_id)
    warehouse = db.get(Warehouse, reversal.warehouse_id)
    out.product_name = product.name if product else None
    out.warehouse_name = warehouse.name if warehouse else None
    return out


# --------------------------- recalculate -------------------------------- #
@router.post("/stock/recalculate", response_model=MessageResponse)
def recalculate_stock(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> MessageResponse:
    """Rebuild the local ledger and balances from scratch (local only)."""
    service = StockService(db)
    stats = service.rebuild_stock(user_id=user.id)
    record_audit(
        db, AuditAction.STOCK_RECALCULATED, user=user, object_type="stock",
        description="Przeliczono lokalne stany magazynowe od nowa",
        new_value=stats,
        ip_address=client_ip(request),
    )
    db.commit()
    return MessageResponse(message="Stany magazynowe przeliczone", detail=stats)
