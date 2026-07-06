"""Product recognition & mapping.

Resolution order for an invoice position (per business rules):

1. ``product_id`` present on the position → direct, CONFIRMED match.
2. A previously CONFIRMED :class:`ProductMapping` with the same source
   signature (name/code/EAN/unit) → CONFIRMED match.
3. A user-defined :class:`ProductAlias` (code / EAN / SKU / name) → CONFIRMED.
4. Exact match on the local product's code → PROPOSED (requires approval).
5. Exact match on EAN → PROPOSED.
6. Exact (normalized) match on name → PROPOSED.
7. No match → position flagged for manual mapping; a PROPOSED
   :class:`ProductMapping` stub without a product is created so it shows up
   in the mapping panel.

All mapping data is stored exclusively locally.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import MappingMatchType, MappingStatus, ProductKind
from app.models.fakturownia import FakturowniaInvoicePosition, FakturowniaProduct
from app.models.product import Product, ProductAlias, ProductMapping
from app.services.parsing import mapping_signature, normalize_text

logger = logging.getLogger(__name__)


def ensure_local_products(db: Session) -> int:
    """Create a local product master row for every mirrored Fakturownia product."""
    created = 0
    fakturownia_products = db.execute(select(FakturowniaProduct)).scalars().all()
    existing_ids = {
        pid for (pid,) in db.execute(
            select(Product.fakturownia_product_id).where(
                Product.fakturownia_product_id.isnot(None)
            )
        )
    }
    for fp in fakturownia_products:
        if fp.fakturownia_id in existing_ids:
            continue
        is_service = bool(fp.is_service_upstream)
        db.add(
            Product(
                fakturownia_product_id=fp.fakturownia_id,
                name=fp.name or f"Produkt {fp.fakturownia_id}",
                code=fp.code,
                ean=fp.ean,
                sku=fp.sku,
                unit=fp.unit,
                kind=str(ProductKind.SERVICE if is_service else ProductKind.STOCK_ITEM),
                is_stock_controlled=not is_service,
                is_active=not fp.disabled,
            )
        )
        created += 1
    db.flush()
    return created


class _MappingIndex:
    """In-memory lookup index built once per mapping run."""

    def __init__(self, db: Session) -> None:
        products = db.execute(select(Product)).scalars().all()
        self.by_fakturownia_id: dict[int, Product] = {
            prod.fakturownia_product_id: prod
            for prod in products
            if prod.fakturownia_product_id is not None
        }
        self.by_code: dict[str, list[Product]] = {}
        self.by_ean: dict[str, list[Product]] = {}
        self.by_name: dict[str, list[Product]] = {}
        for prod in products:
            if prod.code:
                self.by_code.setdefault(normalize_text(prod.code), []).append(prod)
            if prod.ean:
                self.by_ean.setdefault(normalize_text(prod.ean), []).append(prod)
            if prod.name:
                self.by_name.setdefault(normalize_text(prod.name), []).append(prod)

        aliases = db.execute(select(ProductAlias)).scalars().all()
        self.alias_lookup: dict[tuple[str, str], list[int]] = {}
        for alias in aliases:
            key = (alias.alias_type, alias.alias_value_normalized)
            self.alias_lookup.setdefault(key, []).append(alias.product_id)

        confirmed = db.execute(
            select(ProductMapping).where(
                ProductMapping.status == str(MappingStatus.CONFIRMED),
                ProductMapping.product_id.isnot(None),
            )
        ).scalars().all()
        self.confirmed_by_signature: dict[str, ProductMapping] = {
            m.signature: m for m in confirmed
        }


def _resolve_position(
    index: _MappingIndex, position: FakturowniaInvoicePosition
) -> tuple[Product | None, MappingMatchType | None, MappingStatus | None, bool]:
    """Returns (product, match_type, mapping_status, ambiguous)."""
    if position.product_fakturownia_id is not None:
        product = index.by_fakturownia_id.get(position.product_fakturownia_id)
        if product is not None:
            return product, MappingMatchType.PRODUCT_ID, MappingStatus.CONFIRMED, False

    raw = position.raw or {}
    ean = raw.get("ean") or raw.get("ean_code")
    signature = mapping_signature(position.name, position.code, ean, position.quantity_unit)

    confirmed = index.confirmed_by_signature.get(signature)
    if confirmed is not None and confirmed.product_id is not None:
        return _ByIdProxy(confirmed.product_id), MappingMatchType.MANUAL, MappingStatus.CONFIRMED, False

    for alias_type, value in (
        ("CODE", position.code),
        ("EAN", ean),
        ("NAME", position.name),
    ):
        if not value:
            continue
        product_ids = index.alias_lookup.get((alias_type, normalize_text(str(value))))
        if product_ids:
            if len(set(product_ids)) > 1:
                return None, MappingMatchType.ALIAS, None, True
            return _ByIdProxy(product_ids[0]), MappingMatchType.ALIAS, MappingStatus.CONFIRMED, False

    if position.code:
        candidates = index.by_code.get(normalize_text(position.code), [])
        if len(candidates) == 1:
            return candidates[0], MappingMatchType.CODE, MappingStatus.PROPOSED, False
        if len(candidates) > 1:
            return None, MappingMatchType.CODE, None, True

    if ean:
        candidates = index.by_ean.get(normalize_text(str(ean)), [])
        if len(candidates) == 1:
            return candidates[0], MappingMatchType.EAN, MappingStatus.PROPOSED, False
        if len(candidates) > 1:
            return None, MappingMatchType.EAN, None, True

    if position.name:
        candidates = index.by_name.get(normalize_text(position.name), [])
        if len(candidates) == 1:
            return candidates[0], MappingMatchType.NAME, MappingStatus.PROPOSED, False
        if len(candidates) > 1:
            return None, MappingMatchType.NAME, None, True

    return None, None, None, False


class _ByIdProxy:
    """Lightweight stand-in carrying only a product id."""

    def __init__(self, product_id: int) -> None:
        self.id = product_id


def apply_position_mappings(db: Session, only_unmapped: bool = False) -> dict[str, Any]:
    """(Re)resolve product mapping for invoice positions. Local writes only."""
    index = _MappingIndex(db)
    query = select(FakturowniaInvoicePosition)
    if only_unmapped:
        query = query.where(FakturowniaInvoicePosition.mapped_product_id.is_(None))

    stats = {"resolved": 0, "proposed": 0, "unresolved": 0, "ambiguous": 0}
    signatures_needing_mapping: dict[str, FakturowniaInvoicePosition] = {}

    for position in db.execute(query).scalars():
        product, match_type, status, ambiguous = _resolve_position(index, position)
        if ambiguous:
            position.mapped_product_id = None
            position.mapping_status = str(MappingStatus.REJECTED)
            position.mapping_match_type = str(match_type) if match_type else None
            stats["ambiguous"] += 1
            continue
        if product is not None and status == MappingStatus.CONFIRMED:
            position.mapped_product_id = product.id
            position.mapping_status = str(MappingStatus.CONFIRMED)
            position.mapping_match_type = str(match_type)
            stats["resolved"] += 1
        elif product is not None:
            position.mapped_product_id = product.id
            position.mapping_status = str(MappingStatus.PROPOSED)
            position.mapping_match_type = str(match_type)
            stats["proposed"] += 1
            _ensure_mapping_stub(db, index, position, product.id, match_type)
        else:
            position.mapped_product_id = None
            position.mapping_status = None
            position.mapping_match_type = None
            stats["unresolved"] += 1
            raw = position.raw or {}
            sig = mapping_signature(
                position.name, position.code,
                raw.get("ean") or raw.get("ean_code"), position.quantity_unit,
            )
            signatures_needing_mapping.setdefault(sig, position)

    for sig, position in signatures_needing_mapping.items():
        _ensure_mapping_stub(db, index, position, None, None, sig)

    db.flush()
    return stats


def _ensure_mapping_stub(
    db: Session,
    index: _MappingIndex,
    position: FakturowniaInvoicePosition,
    product_id: int | None,
    match_type: MappingMatchType | None,
    signature: str | None = None,
) -> None:
    raw = position.raw or {}
    ean = raw.get("ean") or raw.get("ean_code")
    sig = signature or mapping_signature(
        position.name, position.code, ean, position.quantity_unit
    )
    existing = db.execute(
        select(ProductMapping).where(ProductMapping.signature == sig)
    ).scalars().first()
    if existing is not None:
        return
    db.add(
        ProductMapping(
            source_name=position.name,
            source_code=position.code,
            source_ean=str(ean) if ean else None,
            source_unit=position.quantity_unit,
            signature=sig,
            product_id=product_id,
            match_type=str(match_type or MappingMatchType.MANUAL),
            status=str(MappingStatus.PROPOSED),
            example_invoice_position_id=position.id,
        )
    )


def confirm_mapping(db: Session, mapping: ProductMapping, product_id: int, user_id: int | None) -> None:
    """Confirm a mapping locally and re-apply it to matching positions."""
    mapping.product_id = product_id
    mapping.status = str(MappingStatus.CONFIRMED)
    mapping.confirmed_by_user_id = user_id
    mapping.confirmed_at = datetime.now(timezone.utc)
    db.flush()
    apply_position_mappings(db)


def unmapped_positions_count(db: Session) -> int:
    return db.execute(
        select(func.count(FakturowniaInvoicePosition.id)).where(
            FakturowniaInvoicePosition.mapped_product_id.is_(None)
        )
    ).scalar_one()
