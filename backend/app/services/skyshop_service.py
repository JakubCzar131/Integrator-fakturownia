"""SkyShop integration: mirror refresh, product matching, stock and PIM push.

Everything is built around two rules dictated by the platform limit of one
request per second:

* **read once, decide locally** — the shop catalogue is mirrored into
  ``skyshop_products``; matching and "is it in the shop?" checks never call
  the API,
* **push only deltas** — ``skyshop_product_links`` remembers the last pushed
  stock quantity and the last pushed PIM content hash, so a stable assortment
  produces almost no outbound traffic.

Actual writes are never executed inline: they are enqueued into the
``sync_jobs`` outbox and executed by :mod:`app.services.sync_worker`, which
drains the queue at the allowed pace.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import (
    ProductKind,
    SkyShopLinkStatus,
    StockSource,
    SyncJobStatus,
    SyncJobType,
)
from app.models.fakturownia import FakturowniaProduct, FakturowniaProductStock
from app.models.product import Product
from app.models.skyshop import (
    ProductContent,
    SkyShopCategory,
    SkyShopCategoryMapping,
    SkyShopProduct,
    SkyShopProductLink,
)
from app.models.stock import LocalStockBalance
from app.models.sync import SyncJob
from app.services import parsing as p
from app.services.reconciliation_service import reconciled_stock_map
from app.services.skyshop_client import SkyShopClient, SkyShopError
from app.services.stock_service import get_setting
from app.services.parsing import normalize_text

logger = logging.getLogger(__name__)

ZERO = Decimal("0")

SETTING_SYNC_ENABLED = "skyshop_sync_enabled"
SETTING_DRY_RUN = "skyshop_dry_run"
SETTING_STOCK_SOURCE = "skyshop_stock_source"
SETTING_STOCK_WAREHOUSE_ID = "skyshop_stock_warehouse_id"
SETTING_AUTO_STOCK_PUSH = "skyshop_auto_stock_push"
SETTING_MATCH_BY_NAME = "skyshop_match_by_name"

# Stock pushes must outrun catalogue publications: an oversell costs money.
PRIORITY_STOCK = 3
PRIORITY_PRODUCT = 6
PRIORITY_MIRROR = 8


class SkyShopValidationError(Exception):
    """Raised when a product does not satisfy the pre-publication checks."""


@dataclass
class PublicationIssue:
    product_id: int
    product_name: str
    problems: list[str]


def is_write_enabled(db: Session) -> bool:
    return bool(get_setting(db, SETTING_SYNC_ENABLED, False))


def is_dry_run(db: Session) -> bool:
    return bool(get_setting(db, SETTING_DRY_RUN, True))


def content_hash(product: Product, content: ProductContent | None) -> str:
    """Fingerprint of everything that would be published for a product."""
    payload = {
        "name": product.name,
        "code": product.code,
        "ean": product.ean,
        "sku": product.sku,
        "unit": product.unit,
        "is_active": product.is_active,
        "description_html": content.description_html if content else None,
        "short_description": content.short_description if content else None,
        "images": content.images if content else [],
        "attributes": content.attributes if content else {},
        "price_gross": str(content.price_gross) if content and content.price_gross else None,
        "vat_rate": content.vat_rate if content else None,
        "local_category": content.local_category if content else None,
        "weight": str(content.weight) if content and content.weight else None,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SkyShopService:
    """Local-only orchestration; the client is created lazily, per operation."""

    def __init__(
        self, db: Session, client_factory: Callable[[], SkyShopClient] | None = None
    ) -> None:
        self.db = db
        self._client_factory = client_factory
        self._client: SkyShopClient | None = None

    def client(self) -> SkyShopClient:
        if self._client is None:
            if self._client_factory is None:
                from app.api.deps import build_skyshop_client

                self._client = build_skyshop_client(self.db)
            else:
                self._client = self._client_factory()
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # ------------------------------------------------------------------ #
    # Mirror
    # ------------------------------------------------------------------ #
    def refresh_mirror(self) -> dict[str, Any]:
        """Pull the shop catalogue and categories into the local mirror."""
        client = self.client()
        stats = {"products": 0, "created": 0, "updated": 0, "unchanged": 0, "categories": 0}
        seen: set[str] = set()

        for page in client.iter_pages(client.endpoints.products):
            for item in page:
                skyshop_id = _remote_id(item)
                if not skyshop_id:
                    continue
                seen.add(skyshop_id)
                stats["products"] += 1
                payload_hash = p.payload_hash(item)
                row = self.db.execute(
                    select(SkyShopProduct).where(SkyShopProduct.skyshop_id == skyshop_id)
                ).scalar_one_or_none()
                if row is None:
                    row = SkyShopProduct(skyshop_id=skyshop_id)
                    self.db.add(row)
                    stats["created"] += 1
                elif row.payload_hash == payload_hash:
                    row.last_synced_at = datetime.now(timezone.utc)
                    row.is_deleted_upstream = False
                    stats["unchanged"] += 1
                    continue
                else:
                    stats["updated"] += 1
                row.sku = p.to_str(item.get("sku") or item.get("code") or item.get("symbol"), 255)
                row.ean = p.to_str(item.get("ean") or item.get("ean_code") or item.get("barcode"), 64)
                row.name = p.to_str(item.get("name") or item.get("title"), 1000)
                row.price_gross = p.to_decimal(
                    item.get("price_gross") or item.get("price") or item.get("priceGross")
                )
                row.quantity = p.to_decimal(
                    item.get("quantity") if item.get("quantity") is not None else item.get("stock")
                )
                row.category_skyshop_id = p.to_str(
                    item.get("category_id") or item.get("categoryId"), 64
                )
                row.is_active = (
                    p.to_bool(item.get("active"))
                    if "active" in item
                    else (p.to_bool(item.get("enabled")) if "enabled" in item else None)
                )
                row.raw = item
                row.payload_hash = payload_hash
                row.is_deleted_upstream = False
                row.last_synced_at = datetime.now(timezone.utc)
            self.db.flush()

        for row in self.db.execute(
            select(SkyShopProduct).where(SkyShopProduct.is_deleted_upstream.is_(False))
        ).scalars():
            if row.skyshop_id not in seen:
                row.is_deleted_upstream = True

        stats["categories"] = self._refresh_categories(client)
        self.db.flush()
        return stats

    def _refresh_categories(self, client: SkyShopClient) -> int:
        count = 0
        for page in client.iter_pages(client.endpoints.categories):
            for item in page:
                skyshop_id = _remote_id(item)
                if not skyshop_id:
                    continue
                count += 1
                row = self.db.execute(
                    select(SkyShopCategory).where(SkyShopCategory.skyshop_id == skyshop_id)
                ).scalar_one_or_none()
                if row is None:
                    row = SkyShopCategory(skyshop_id=skyshop_id)
                    self.db.add(row)
                row.name = p.to_str(item.get("name") or item.get("title"), 500)
                row.parent_skyshop_id = p.to_str(
                    item.get("parent_id") or item.get("parentId"), 64
                )
                row.path = p.to_str(item.get("path") or item.get("full_name"))
                row.raw = item
                row.last_synced_at = datetime.now(timezone.utc)
            self.db.flush()
        return count

    # ------------------------------------------------------------------ #
    # Matching (mirror only — zero API calls)
    # ------------------------------------------------------------------ #
    def match_links(self, only_unlinked: bool = True) -> dict[str, Any]:
        by_sku: dict[str, list[SkyShopProduct]] = {}
        by_ean: dict[str, list[SkyShopProduct]] = {}
        by_name: dict[str, list[SkyShopProduct]] = {}
        for mirror in self.db.execute(
            select(SkyShopProduct).where(SkyShopProduct.is_deleted_upstream.is_(False))
        ).scalars():
            if mirror.sku:
                by_sku.setdefault(normalize_text(mirror.sku), []).append(mirror)
            if mirror.ean:
                by_ean.setdefault(normalize_text(mirror.ean), []).append(mirror)
            if mirror.name:
                by_name.setdefault(normalize_text(mirror.name), []).append(mirror)

        match_by_name = bool(get_setting(self.db, SETTING_MATCH_BY_NAME, False))
        stats = {"linked": 0, "missing": 0, "ambiguous": 0, "skipped": 0}

        products = self.db.execute(
            select(Product).where(Product.kind != str(ProductKind.SERVICE))
        ).scalars().all()
        links = {
            link.product_id: link
            for link in self.db.execute(select(SkyShopProductLink)).scalars()
        }

        for product in products:
            link = links.get(product.id)
            if link is None:
                link = SkyShopProductLink(product_id=product.id)
                self.db.add(link)
                links[product.id] = link
            if link.status == str(SkyShopLinkStatus.EXCLUDED):
                stats["skipped"] += 1
                continue
            if only_unlinked and link.status == str(SkyShopLinkStatus.LINKED) and link.skyshop_id:
                stats["skipped"] += 1
                continue
            if link.match_type == "MANUAL" and link.skyshop_id:
                stats["skipped"] += 1
                continue

            candidates: list[SkyShopProduct] = []
            match_type: str | None = None
            for value, bucket, label in (
                (product.sku or product.code, by_sku, "SKU"),
                (product.ean, by_ean, "EAN"),
            ):
                if value:
                    candidates = bucket.get(normalize_text(str(value)), [])
                    if candidates:
                        match_type = label
                        break
            if not candidates and match_by_name and product.name:
                candidates = by_name.get(normalize_text(product.name), [])
                match_type = "NAME" if candidates else None

            if len(candidates) == 1:
                link.skyshop_id = candidates[0].skyshop_id
                link.status = str(SkyShopLinkStatus.LINKED)
                link.match_type = match_type
                link.candidate_skyshop_ids = None
                stats["linked"] += 1
            elif len(candidates) > 1:
                # Never resolve a conflict automatically — an operator decides.
                link.status = str(SkyShopLinkStatus.AMBIGUOUS)
                link.match_type = match_type
                link.candidate_skyshop_ids = [c.skyshop_id for c in candidates]
                stats["ambiguous"] += 1
            else:
                if link.status != str(SkyShopLinkStatus.PENDING_CREATE):
                    link.status = str(SkyShopLinkStatus.MISSING)
                link.candidate_skyshop_ids = None
                stats["missing"] += 1

        self.db.flush()
        return stats

    def ensure_link(self, product_id: int) -> SkyShopProductLink:
        link = self.db.execute(
            select(SkyShopProductLink).where(SkyShopProductLink.product_id == product_id)
        ).scalar_one_or_none()
        if link is None:
            link = SkyShopProductLink(product_id=product_id)
            self.db.add(link)
            self.db.flush()
        return link

    # ------------------------------------------------------------------ #
    # Stock source
    # ------------------------------------------------------------------ #
    def stock_map(self) -> dict[int, Decimal]:
        """Quantity to publish per local product, per the configured source."""
        source = str(get_setting(self.db, SETTING_STOCK_SOURCE, str(StockSource.LOCAL_LEDGER)))
        warehouse_id = get_setting(self.db, SETTING_STOCK_WAREHOUSE_ID, None)

        if source == str(StockSource.RECONCILED):
            return reconciled_stock_map(self.db)

        if source == str(StockSource.FAKTUROWNIA):
            if warehouse_id:
                rows = self.db.execute(
                    select(
                        Product.id,
                        func.sum(FakturowniaProductStock.quantity),
                    )
                    .join(
                        FakturowniaProductStock,
                        FakturowniaProductStock.product_fakturownia_id
                        == Product.fakturownia_product_id,
                    )
                    .where(FakturowniaProductStock.warehouse_fakturownia_id == int(warehouse_id))
                    .group_by(Product.id)
                ).all()
            else:
                rows = self.db.execute(
                    select(Product.id, FakturowniaProduct.quantity).join(
                        FakturowniaProduct,
                        FakturowniaProduct.fakturownia_id == Product.fakturownia_product_id,
                    )
                ).all()
            return {pid: Decimal(str(qty or 0)) for pid, qty in rows}

        query = select(
            LocalStockBalance.product_id, func.sum(LocalStockBalance.quantity)
        ).group_by(LocalStockBalance.product_id)
        if warehouse_id:
            query = query.where(LocalStockBalance.warehouse_id == int(warehouse_id))
        return {
            pid: Decimal(str(qty or 0))
            for pid, qty in self.db.execute(query).all()
        }

    # ------------------------------------------------------------------ #
    # Enqueue: stock delta
    # ------------------------------------------------------------------ #
    def enqueue_stock_sync(
        self,
        user_id: int | None = None,
        product_ids: list[int] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Queue a stock push for products whose quantity actually changed."""
        stock = self.stock_map()
        links = {
            link.product_id: link
            for link in self.db.execute(
                select(SkyShopProductLink).where(
                    SkyShopProductLink.status == str(SkyShopLinkStatus.LINKED),
                    SkyShopProductLink.skyshop_id.isnot(None),
                )
            ).scalars()
        }
        if product_ids is not None:
            links = {pid: link for pid, link in links.items() if pid in set(product_ids)}

        stats = {"considered": len(links), "enqueued": 0, "unchanged": 0}
        for product_id, link in links.items():
            quantity = stock.get(product_id, ZERO)
            if not force and link.last_pushed_stock is not None:
                if Decimal(str(link.last_pushed_stock)) == quantity:
                    stats["unchanged"] += 1
                    continue
            self.enqueue_job(
                SyncJobType.SKYSHOP_STOCK_PUSH,
                payload={
                    "product_id": product_id,
                    "skyshop_id": link.skyshop_id,
                    "quantity": str(quantity),
                },
                dedupe_key=f"stock:product:{product_id}",
                priority=PRIORITY_STOCK,
                product_id=product_id,
                user_id=user_id,
            )
            stats["enqueued"] += 1
        self.db.flush()
        return stats

    # ------------------------------------------------------------------ #
    # Enqueue: product publication
    # ------------------------------------------------------------------ #
    def validate_for_publication(self, product: Product) -> list[str]:
        content = self.db.get(ProductContent, product.id)
        problems: list[str] = []
        if not product.is_active:
            problems.append("produkt jest nieaktywny")
        if product.kind == str(ProductKind.SERVICE):
            problems.append("produkt jest usługą (nie trafia na sklep)")
        if content is None:
            problems.append("brak danych PIM (opis, cena, kategoria)")
            return problems
        if not content.is_publishable:
            problems.append("produkt oznaczony jako niepublikowalny")
        if content.price_gross is None or content.price_gross <= 0:
            problems.append("brak ceny brutto")
        if not (content.short_description or content.description_html):
            problems.append("brak opisu")
        if not content.local_category:
            problems.append("brak kategorii lokalnej")
        elif self._skyshop_category_id(content.local_category) is None:
            problems.append(
                f"kategoria „{content.local_category}” nie jest zmapowana na kategorię SkyShop"
            )
        return problems

    def enqueue_product_push(
        self,
        product_ids: list[int],
        mode: str = "auto",
        user_id: int | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        stats: dict[str, Any] = {"enqueued": 0, "unchanged": 0, "rejected": []}
        for product_id in product_ids:
            product = self.db.get(Product, product_id)
            if product is None:
                stats["rejected"].append(
                    {"product_id": product_id, "problems": ["produkt nie istnieje"]}
                )
                continue
            problems = self.validate_for_publication(product)
            if problems:
                stats["rejected"].append(
                    {"product_id": product_id, "product_name": product.name, "problems": problems}
                )
                continue

            link = self.ensure_link(product_id)
            content = self.db.get(ProductContent, product_id)
            new_hash = content_hash(product, content)
            is_update = bool(link.skyshop_id) if mode == "auto" else mode == "update"
            if is_update and not force and link.last_pushed_content_hash == new_hash:
                stats["unchanged"] += 1
                continue
            if not is_update:
                link.status = str(SkyShopLinkStatus.PENDING_CREATE)

            job_type = (
                SyncJobType.SKYSHOP_PRODUCT_UPDATE if is_update
                else SyncJobType.SKYSHOP_PRODUCT_CREATE
            )
            self.enqueue_job(
                job_type,
                payload={
                    "product_id": product_id,
                    "skyshop_id": link.skyshop_id,
                    "content_hash": new_hash,
                },
                dedupe_key=f"product:{product_id}",
                priority=PRIORITY_PRODUCT,
                product_id=product_id,
                user_id=user_id,
            )
            stats["enqueued"] += 1
        self.db.flush()
        return stats

    # ------------------------------------------------------------------ #
    # Outbox
    # ------------------------------------------------------------------ #
    def enqueue_job(
        self,
        job_type: SyncJobType,
        payload: dict[str, Any],
        dedupe_key: str | None = None,
        priority: int = 5,
        product_id: int | None = None,
        user_id: int | None = None,
        max_attempts: int = 5,
    ) -> SyncJob:
        """Insert (or refresh) a queued job.

        Re-queueing work that is still pending replaces its payload instead of
        adding a second job — with one request per second available, duplicate
        pushes are pure waste.
        """
        existing = None
        if dedupe_key:
            existing = self.db.execute(
                select(SyncJob).where(
                    SyncJob.dedupe_key == dedupe_key,
                    SyncJob.status == str(SyncJobStatus.PENDING),
                )
            ).scalars().first()
        if existing is not None:
            existing.payload = payload
            existing.priority = min(existing.priority, priority)
            existing.next_attempt_at = datetime.now(timezone.utc)
            existing.job_type = str(job_type)
            self.db.flush()
            return existing

        job = SyncJob(
            provider="SKYSHOP",
            job_type=str(job_type),
            dedupe_key=dedupe_key,
            payload=payload,
            status=str(SyncJobStatus.PENDING),
            priority=priority,
            max_attempts=max_attempts,
            next_attempt_at=datetime.now(timezone.utc),
            product_id=product_id,
            created_by_user_id=user_id,
        )
        self.db.add(job)
        self.db.flush()
        return job

    # ------------------------------------------------------------------ #
    # Job execution (called by the worker)
    # ------------------------------------------------------------------ #
    def execute_job(self, job: SyncJob) -> dict[str, Any]:
        handlers = {
            str(SyncJobType.SKYSHOP_STOCK_PUSH): self._run_stock_push,
            str(SyncJobType.SKYSHOP_PRODUCT_CREATE): self._run_product_create,
            str(SyncJobType.SKYSHOP_PRODUCT_UPDATE): self._run_product_update,
            str(SyncJobType.SKYSHOP_MIRROR_REFRESH): lambda _job: self.refresh_mirror(),
        }
        handler = handlers.get(job.job_type)
        if handler is None:
            raise SkyShopError(f"Nieobsługiwany typ zadania: {job.job_type}")
        return handler(job)

    def _run_stock_push(self, job: SyncJob) -> dict[str, Any]:
        payload = job.payload or {}
        product_id = int(payload["product_id"])
        link = self.ensure_link(product_id)
        skyshop_id = payload.get("skyshop_id") or link.skyshop_id
        if not skyshop_id:
            raise SkyShopError(
                "Produkt nie jest powiązany z produktem w SkyShop — uruchom dopasowanie"
            )
        quantity = Decimal(str(payload.get("quantity", "0")))
        client = self.client()
        response = client.write(
            "POST",
            client.endpoints.stock.format(id=skyshop_id),
            {"product_id": skyshop_id, "quantity": str(quantity)},
        )
        link.last_pushed_stock = quantity
        link.last_pushed_at = datetime.now(timezone.utc)
        link.last_error = None
        self.db.flush()
        return {"quantity": str(quantity), "response": response}

    def _run_product_create(self, job: SyncJob) -> dict[str, Any]:
        payload = job.payload or {}
        product_id = int(payload["product_id"])
        product = self.db.get(Product, product_id)
        if product is None:
            raise SkyShopError(f"Produkt {product_id} nie istnieje")
        problems = self.validate_for_publication(product)
        if problems:
            raise SkyShopValidationError("; ".join(problems))

        body = self.build_product_payload(product)
        client = self.client()
        response = client.write("POST", client.endpoints.products, body)
        link = self.ensure_link(product_id)
        new_id = _remote_id(response) or _remote_id(response.get("data") or {})
        if new_id:
            link.skyshop_id = new_id
            link.status = str(SkyShopLinkStatus.LINKED)
            link.match_type = link.match_type or "MANUAL"
        link.last_pushed_content_hash = payload.get("content_hash") or content_hash(
            product, self.db.get(ProductContent, product_id)
        )
        link.last_pushed_at = datetime.now(timezone.utc)
        link.last_error = None
        self.db.flush()
        return {"skyshop_id": new_id, "response": response}

    def _run_product_update(self, job: SyncJob) -> dict[str, Any]:
        payload = job.payload or {}
        product_id = int(payload["product_id"])
        product = self.db.get(Product, product_id)
        if product is None:
            raise SkyShopError(f"Produkt {product_id} nie istnieje")
        link = self.ensure_link(product_id)
        skyshop_id = payload.get("skyshop_id") or link.skyshop_id
        if not skyshop_id:
            raise SkyShopError("Brak powiązania z produktem w SkyShop — najpierw utwórz produkt")
        problems = self.validate_for_publication(product)
        if problems:
            raise SkyShopValidationError("; ".join(problems))

        body = self.build_product_payload(product)
        client = self.client()
        response = client.write(
            "PUT", client.endpoints.product.format(id=skyshop_id), body
        )
        link.last_pushed_content_hash = payload.get("content_hash") or content_hash(
            product, self.db.get(ProductContent, product_id)
        )
        link.last_pushed_at = datetime.now(timezone.utc)
        link.last_error = None
        self.db.flush()
        return {"skyshop_id": skyshop_id, "response": response}

    # ------------------------------------------------------------------ #
    # Payload building
    # ------------------------------------------------------------------ #
    def build_product_payload(self, product: Product) -> dict[str, Any]:
        content = self.db.get(ProductContent, product.id)
        stock = self.stock_map().get(product.id, ZERO)
        payload: dict[str, Any] = {
            "name": product.name,
            "sku": product.sku or product.code,
            "ean": product.ean,
            "unit": product.unit,
            "active": product.is_active,
            "quantity": str(stock),
        }
        if content is not None:
            payload.update(
                {
                    "description": content.description_html,
                    "short_description": content.short_description,
                    "price_gross": (
                        str(content.price_gross) if content.price_gross is not None else None
                    ),
                    "vat_rate": content.vat_rate,
                    "weight": str(content.weight) if content.weight is not None else None,
                    "images": content.images or [],
                    "attributes": content.attributes or {},
                }
            )
            category_id = self._skyshop_category_id(content.local_category)
            if category_id:
                payload["category_id"] = category_id
        return {k: v for k, v in payload.items() if v is not None}

    def _skyshop_category_id(self, local_category: str | None) -> str | None:
        if not local_category:
            return None
        row = self.db.execute(
            select(SkyShopCategoryMapping).where(
                SkyShopCategoryMapping.local_category == local_category
            )
        ).scalar_one_or_none()
        return row.skyshop_category_id if row else None

    # ------------------------------------------------------------------ #
    # Overview for the dashboard / UI
    # ------------------------------------------------------------------ #
    def summary(self) -> dict[str, Any]:
        status_counts = dict(
            self.db.execute(
                select(SkyShopProductLink.status, func.count(SkyShopProductLink.id))
                .group_by(SkyShopProductLink.status)
            ).all()
        )
        job_counts = dict(
            self.db.execute(
                select(SyncJob.status, func.count(SyncJob.id)).group_by(SyncJob.status)
            ).all()
        )
        last_push = self.db.execute(
            select(func.max(SkyShopProductLink.last_pushed_at))
        ).scalar_one_or_none()
        mirror_count = self.db.execute(
            select(func.count(SkyShopProduct.id)).where(
                SkyShopProduct.is_deleted_upstream.is_(False)
            )
        ).scalar_one()
        mirror_synced_at = self.db.execute(
            select(func.max(SkyShopProduct.last_synced_at))
        ).scalar_one_or_none()
        return {
            "write_enabled": is_write_enabled(self.db),
            "dry_run": is_dry_run(self.db),
            "stock_source": str(
                get_setting(self.db, SETTING_STOCK_SOURCE, str(StockSource.LOCAL_LEDGER))
            ),
            "link_status_counts": status_counts,
            "job_status_counts": job_counts,
            "mirror_product_count": mirror_count,
            "mirror_synced_at": mirror_synced_at,
            "last_push_at": last_push,
            "pending_jobs": job_counts.get(str(SyncJobStatus.PENDING), 0),
            "failed_jobs": job_counts.get(str(SyncJobStatus.FAILED), 0),
        }


def backoff_delay(attempts: int) -> timedelta:
    """Exponential backoff for a failed job, capped at 30 minutes."""
    return timedelta(seconds=min(30 * 60, 30 * (2 ** max(0, attempts - 1))))


def _remote_id(item: dict[str, Any] | None) -> str | None:
    if not isinstance(item, dict):
        return None
    for key in ("id", "product_id", "productId", "skyshop_id"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return None
