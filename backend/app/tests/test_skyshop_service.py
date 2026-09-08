"""SkyShop orchestration: mirror, matching, delta pushes and the outbox worker."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.enums import StockSource, SyncJobStatus, SyncJobType
from app.models.product import Product
from app.models.settings import AppSetting
from app.models.skyshop import (
    ProductContent,
    SkyShopCategory,
    SkyShopCategoryMapping,
    SkyShopProduct,
    SkyShopProductLink,
)
from app.models.sync import SyncJob
from app.services import skyshop_client as client_module
from app.services.skyshop_service import (
    SETTING_MATCH_BY_NAME,
    SETTING_STOCK_SOURCE,
    SkyShopService,
    backoff_delay,
    content_hash,
)
from app.services.stock_service import StockService
from app.services.sync_service import SyncService
from app.services.sync_worker import claim_jobs, process_pending_jobs
from app.tests.fixtures import FakeFakturowniaClient
from app.tests.skyshop_fixtures import FakeShop, make_client


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch) -> None:
    monkeypatch.setattr(client_module.time, "sleep", lambda _seconds: None)


def _set(db, key: str, value) -> None:
    row = db.execute(select(AppSetting).where(AppSetting.key == key)).scalar_one_or_none()
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    db.flush()


def _service(db, shop: FakeShop | None = None, **client_kwargs) -> tuple[SkyShopService, FakeShop]:
    shop = shop or FakeShop()

    def factory():
        client, _ = make_client(shop, **client_kwargs)
        return client

    return SkyShopService(db, client_factory=factory), shop


def _prepared(db, shop: FakeShop | None = None, **client_kwargs):
    """Synced Fakturownia data plus a refreshed shop mirror."""
    SyncService(db, FakeFakturowniaClient()).run_full_sync()
    service, shop = _service(db, shop, **client_kwargs)
    service.refresh_mirror()
    return service, shop


def _product(db, name: str) -> Product:
    return db.execute(select(Product).where(Product.name == name)).scalar_one()


def _link(db, product_id: int) -> SkyShopProductLink:
    return db.execute(
        select(SkyShopProductLink).where(SkyShopProductLink.product_id == product_id)
    ).scalar_one()


# ------------------------------- mirror ---------------------------------- #
def test_mirror_refresh_imports_products_and_categories(db) -> None:
    service, shop = _service(db)
    stats = service.refresh_mirror()
    assert stats == {"products": 2, "created": 2, "updated": 0, "unchanged": 0, "categories": 2}

    mirrored = db.execute(
        select(SkyShopProduct).order_by(SkyShopProduct.skyshop_id)
    ).scalars().all()
    assert [row.sku for row in mirrored] == ["WID-A", "WID-B"]
    assert mirrored[0].quantity == Decimal("40.0000")
    assert mirrored[0].price_gross == Decimal("123.00")
    assert mirrored[0].category_skyshop_id == "C-10"
    assert mirrored[0].is_active is True
    assert db.execute(select(func.count(SkyShopCategory.id))).scalar_one() == 2


def test_unchanged_products_are_recognized_by_payload_hash(db) -> None:
    service, shop = _service(db)
    service.refresh_mirror()
    stats = service.refresh_mirror()
    assert stats["unchanged"] == 2
    assert stats["created"] == 0
    assert db.execute(select(func.count(SkyShopProduct.id))).scalar_one() == 2


def test_changed_and_withdrawn_products_are_tracked(db) -> None:
    service, shop = _service(db)
    service.refresh_mirror()

    shop.products = [{**shop.products[0], "quantity": "11"}]
    stats = service.refresh_mirror()
    assert stats == {"products": 1, "created": 0, "updated": 1, "unchanged": 0, "categories": 2}

    rows = {row.skyshop_id: row for row in db.execute(select(SkyShopProduct)).scalars()}
    assert rows["S-1"].quantity == Decimal("11.0000")
    # Products that vanished from the shop stay in the mirror, flagged.
    assert rows["S-2"].is_deleted_upstream is True
    assert rows["S-1"].is_deleted_upstream is False


# ------------------------------ matching --------------------------------- #
def test_matching_links_by_sku_without_touching_the_api(db) -> None:
    service, shop = _prepared(db)
    api_calls = len(shop.requests)

    stats = service.match_links()
    assert len(shop.requests) == api_calls  # matching is a local operation

    widget_a = _product(db, "Widget A")
    link = _link(db, widget_a.id)
    assert link.skyshop_id == "S-1"
    assert link.status == "LINKED"
    assert link.match_type == "SKU"
    assert stats["linked"] == 2


def test_matching_falls_back_to_ean(db) -> None:
    shop = FakeShop(products=[
        {"id": "S-7", "sku": "INNY-KOD", "ean": "5901234567890", "name": "Widget A z hurtu"},
    ])
    service, _ = _prepared(db, shop)
    service.match_links()

    link = _link(db, _product(db, "Widget A").id)
    assert (link.skyshop_id, link.match_type, link.status) == ("S-7", "EAN", "LINKED")


def test_conflicting_candidates_are_never_resolved_automatically(db) -> None:
    shop = FakeShop(products=[
        {"id": "S-1", "sku": "WID-A", "name": "Widget A"},
        {"id": "S-2", "sku": "WID-A", "name": "Widget A (duplikat)"},
    ])
    service, _ = _prepared(db, shop)
    stats = service.match_links()

    link = _link(db, _product(db, "Widget A").id)
    assert link.status == "AMBIGUOUS"
    assert link.skyshop_id is None
    assert sorted(link.candidate_skyshop_ids) == ["S-1", "S-2"]
    assert stats["ambiguous"] == 1


def test_products_absent_from_the_shop_are_marked_missing(db) -> None:
    service, _ = _prepared(db, FakeShop(products=[]))
    stats = service.match_links()
    assert stats["missing"] >= 1
    assert _link(db, _product(db, "Widget A").id).status == "MISSING"


def test_services_are_not_offered_to_the_shop(db) -> None:
    service, _ = _prepared(db)
    service.match_links()
    montaz = _product(db, "Usługa montażu")
    assert db.execute(
        select(SkyShopProductLink).where(SkyShopProductLink.product_id == montaz.id)
    ).scalar_one_or_none() is None


def test_manual_and_excluded_decisions_survive_rematching(db) -> None:
    service, _ = _prepared(db)
    widget_a = _product(db, "Widget A")
    widget_b = _product(db, "Widget B")

    manual = service.ensure_link(widget_a.id)
    manual.skyshop_id = "S-MANUAL"
    manual.match_type = "MANUAL"
    manual.status = "LINKED"
    excluded = service.ensure_link(widget_b.id)
    excluded.status = "EXCLUDED"
    db.flush()

    stats = service.match_links(only_unlinked=False)
    assert stats["skipped"] == 2
    assert _link(db, widget_a.id).skyshop_id == "S-MANUAL"
    assert _link(db, widget_b.id).status == "EXCLUDED"


def test_name_matching_is_opt_in(db) -> None:
    shop = FakeShop(products=[{"id": "S-5", "sku": None, "ean": None, "name": "Widget A"}])
    service, _ = _prepared(db, shop)
    service.match_links()
    widget_a = _product(db, "Widget A")
    assert _link(db, widget_a.id).status == "MISSING"

    _set(db, SETTING_MATCH_BY_NAME, True)
    service.match_links()
    link = _link(db, widget_a.id)
    assert (link.status, link.match_type) == ("LINKED", "NAME")


# ----------------------------- stock source ------------------------------ #
def test_stock_source_selects_which_figure_is_published(db) -> None:
    service, _ = _prepared(db)
    widget_a = _product(db, "Widget A")

    # Default: the local ledger (0 opening − 10 sold + 2 returned = −8).
    assert service.stock_map()[widget_a.id] == Decimal("-8.0000")

    _set(db, SETTING_STOCK_SOURCE, str(StockSource.FAKTUROWNIA))
    assert service.stock_map()[widget_a.id] == Decimal("50.0000")

    _set(db, SETTING_STOCK_SOURCE, str(StockSource.RECONCILED))
    assert service.stock_map()[widget_a.id] == Decimal("17.0000")


# --------------------------- stock delta push ---------------------------- #
def test_only_changed_quantities_are_enqueued(db) -> None:
    service, _ = _prepared(db)
    service.match_links()
    widget_a = _product(db, "Widget A")

    first = service.enqueue_stock_sync()
    assert first["enqueued"] == 2

    jobs = db.execute(select(SyncJob)).scalars().all()
    assert {job.job_type for job in jobs} == {str(SyncJobType.SKYSHOP_STOCK_PUSH)}
    assert {job.dedupe_key for job in jobs} == {
        f"stock:product:{widget_a.id}",
        f"stock:product:{_product(db, 'Widget B').id}",
    }

    # Pretend the queue drained: nothing changed, so nothing is re-sent.
    for link in db.execute(select(SkyShopProductLink)).scalars():
        link.last_pushed_stock = service.stock_map().get(link.product_id)
    db.flush()
    second = service.enqueue_stock_sync()
    assert second == {"considered": 2, "enqueued": 0, "unchanged": 2}

    assert service.enqueue_stock_sync(force=True)["enqueued"] == 2


def test_unlinked_products_are_not_enqueued(db) -> None:
    service, _ = _prepared(db, FakeShop(products=[]))
    service.match_links()
    assert service.enqueue_stock_sync() == {"considered": 0, "enqueued": 0, "unchanged": 0}
    assert db.execute(select(func.count(SyncJob.id))).scalar_one() == 0


def test_requeuing_replaces_the_pending_job_instead_of_duplicating_it(db) -> None:
    service, _ = _prepared(db)
    service.match_links()
    widget_a = _product(db, "Widget A")

    service.enqueue_stock_sync(product_ids=[widget_a.id])
    StockService(db).create_adjustment(
        product_id=widget_a.id, warehouse_id=1, quantity_change=Decimal("100"),
        description="Dostawa poza systemem",
        occurred_at=datetime(2025, 3, 1, tzinfo=timezone.utc), user_id=None,
    )
    StockService(db).rebuild_stock()
    service.enqueue_stock_sync(product_ids=[widget_a.id])

    jobs = db.execute(select(SyncJob)).scalars().all()
    assert len(jobs) == 1  # one request per second: duplicates are pure waste
    assert Decimal(jobs[0].payload["quantity"]) == Decimal("92")


# ---------------------------- publication -------------------------------- #
def _publishable_content(db, product_id: int, **overrides) -> ProductContent:
    values = {
        "product_id": product_id,
        "short_description": "Solidny widget",
        "price_gross": Decimal("123.00"),
        "local_category": "Elektronika",
        "is_publishable": True,
    }
    values.update(overrides)
    content = ProductContent(**values)
    db.add(content)
    mapped = db.execute(
        select(SkyShopCategoryMapping).where(
            SkyShopCategoryMapping.local_category == "Elektronika"
        )
    ).scalar_one_or_none()
    if mapped is None:
        db.add(
            SkyShopCategoryMapping(local_category="Elektronika", skyshop_category_id="C-10")
        )
    db.flush()
    return content


def test_publication_requirements_are_reported_before_anything_is_sent(db) -> None:
    service, _ = _prepared(db)
    widget_a = _product(db, "Widget A")

    assert service.validate_for_publication(widget_a) == [
        "brak danych PIM (opis, cena, kategoria)"
    ]

    content = _publishable_content(
        db, widget_a.id, short_description=None, price_gross=None,
        local_category="Nieistniejąca", is_publishable=False,
    )
    problems = service.validate_for_publication(widget_a)
    assert "produkt oznaczony jako niepublikowalny" in problems
    assert "brak ceny brutto" in problems
    assert "brak opisu" in problems
    assert any("nie jest zmapowana" in problem for problem in problems)

    content.is_publishable = True
    content.short_description = "Opis"
    content.price_gross = Decimal("99.00")
    content.local_category = "Elektronika"
    db.flush()
    assert service.validate_for_publication(widget_a) == []


def test_service_products_are_rejected_from_publication(db) -> None:
    service, _ = _prepared(db)
    montaz = _product(db, "Usługa montażu")
    _publishable_content(db, montaz.id)
    assert "produkt jest usługą (nie trafia na sklep)" in service.validate_for_publication(montaz)


def test_push_enqueues_create_for_new_and_update_for_linked_products(db) -> None:
    service, _ = _prepared(db)
    service.match_links()
    widget_a = _product(db, "Widget A")
    _publishable_content(db, widget_a.id)

    linked = service.enqueue_product_push([widget_a.id])
    assert linked["enqueued"] == 1
    job = db.execute(select(SyncJob)).scalars().one()
    assert job.job_type == str(SyncJobType.SKYSHOP_PRODUCT_UPDATE)
    assert job.priority > 3  # stock pushes must outrun publications

    link = _link(db, widget_a.id)
    link.skyshop_id = None
    link.status = "MISSING"
    db.flush()
    service.enqueue_product_push([widget_a.id])
    assert db.execute(select(SyncJob)).scalars().one().job_type == str(
        SyncJobType.SKYSHOP_PRODUCT_CREATE
    )
    assert _link(db, widget_a.id).status == "PENDING_CREATE"


def test_unchanged_content_is_not_republished(db) -> None:
    service, _ = _prepared(db)
    service.match_links()
    widget_a = _product(db, "Widget A")
    content = _publishable_content(db, widget_a.id)

    link = _link(db, widget_a.id)
    link.last_pushed_content_hash = content_hash(widget_a, content)
    db.flush()
    assert service.enqueue_product_push([widget_a.id]) == {
        "enqueued": 0, "unchanged": 1, "rejected": []
    }

    content.short_description = "Zmieniony opis"
    db.flush()
    assert service.enqueue_product_push([widget_a.id])["enqueued"] == 1


def test_invalid_products_are_reported_and_never_queued(db) -> None:
    service, _ = _prepared(db)
    widget_a = _product(db, "Widget A")
    stats = service.enqueue_product_push([widget_a.id, 9999])
    assert stats["enqueued"] == 0
    assert {entry["product_id"] for entry in stats["rejected"]} == {widget_a.id, 9999}
    assert db.execute(select(func.count(SyncJob.id))).scalar_one() == 0


def test_payload_carries_pim_content_and_the_mapped_category(db) -> None:
    service, _ = _prepared(db)
    widget_a = _product(db, "Widget A")
    _publishable_content(
        db, widget_a.id,
        description_html="<p>Opis</p>",
        images=[{"url": "https://example.pl/a.jpg", "position": 1}],
        attributes={"Kolor": "czerwony"},
        vat_rate="23",
        weight=Decimal("1.250"),
    )
    payload = service.build_product_payload(widget_a)
    assert payload["sku"] == "WID-A"
    assert payload["ean"] == "5901234567890"
    assert payload["category_id"] == "C-10"
    assert payload["description"] == "<p>Opis</p>"
    assert payload["attributes"] == {"Kolor": "czerwony"}
    assert payload["images"][0]["url"] == "https://example.pl/a.jpg"
    assert payload["weight"] == "1.250"

    # Fields the shop has no value for are omitted rather than sent as null.
    widget_b = _product(db, "Widget B")
    _publishable_content(db, widget_b.id)
    assert "ean" not in service.build_product_payload(widget_b)


# ------------------------------- worker ---------------------------------- #
def test_worker_pushes_stock_and_records_what_was_sent(db) -> None:
    service, shop = _prepared(db)
    service.match_links()
    widget_a = _product(db, "Widget A")
    service.enqueue_stock_sync(product_ids=[widget_a.id])
    db.commit()

    stats = process_pending_jobs(db, limit=5, service=service)
    assert stats["success"] == 1
    job = db.execute(select(SyncJob)).scalars().one()
    assert job.status == "SUCCESS"
    assert job.finished_at is not None
    assert job.attempts == 1

    link = _link(db, widget_a.id)
    assert link.last_pushed_stock == Decimal("-8")
    assert link.last_pushed_at is not None
    assert link.last_error is None


def test_worker_creates_the_product_and_links_the_returned_id(db) -> None:
    service, shop = _prepared(db, FakeShop(products=[]))
    widget_a = _product(db, "Widget A")
    _publishable_content(db, widget_a.id)
    service.enqueue_product_push([widget_a.id], mode="create")
    db.commit()

    assert process_pending_jobs(db, service=service)["success"] == 1
    link = _link(db, widget_a.id)
    assert link.skyshop_id == "S-99"
    assert link.status == "LINKED"
    assert link.last_pushed_content_hash
    assert [request.path for request in shop.writes] == ["/api/products"]


def test_kill_switch_leaves_the_queue_intact_and_skips_the_job(db) -> None:
    service, shop = _prepared(db, write_enabled=False)
    service.match_links()
    widget_a = _product(db, "Widget A")
    service.enqueue_stock_sync(product_ids=[widget_a.id])
    db.commit()

    stats = process_pending_jobs(db, service=service)
    assert stats == {"claimed": 1, "success": 0, "failed": 0, "skipped": 1, "retry": 0}
    job = db.execute(select(SyncJob)).scalars().one()
    assert job.status == "SKIPPED"
    assert "skyshop_sync_enabled" in job.last_error
    assert shop.writes == []
    # The link must not pretend a quantity was published.
    assert _link(db, widget_a.id).last_pushed_stock is None


def test_dry_run_completes_the_job_without_calling_the_shop(db) -> None:
    service, shop = _prepared(db, dry_run=True)
    service.match_links()
    widget_a = _product(db, "Widget A")
    service.enqueue_stock_sync(product_ids=[widget_a.id])
    db.commit()

    assert process_pending_jobs(db, service=service)["success"] == 1
    assert shop.writes == []
    assert db.execute(select(SyncJob)).scalars().one().result["response"]["dry_run"] is True


def test_transient_failures_are_retried_with_growing_backoff(db) -> None:
    service, shop = _prepared(db)
    service.match_links()
    widget_a = _product(db, "Widget A")
    service.enqueue_stock_sync(product_ids=[widget_a.id])
    db.commit()
    shop.failures = [500] * 20

    before = datetime.now(timezone.utc)
    stats = process_pending_jobs(db, service=service)
    assert stats["retry"] == 1
    job = db.execute(select(SyncJob)).scalars().one()
    assert job.status == "PENDING"
    assert job.attempts == 1
    assert job.last_error
    assert job.next_attempt_at.replace(tzinfo=timezone.utc) > before


def test_a_job_dead_letters_after_exhausting_its_attempts(db) -> None:
    service, shop = _prepared(db)
    service.match_links()
    widget_a = _product(db, "Widget A")
    service.enqueue_stock_sync(product_ids=[widget_a.id])
    job = db.execute(select(SyncJob)).scalars().one()
    job.max_attempts = 2
    db.commit()
    shop.failures = [500] * 40

    process_pending_jobs(db, service=service)
    job = db.execute(select(SyncJob)).scalars().one()
    job.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    stats = process_pending_jobs(db, service=service)

    assert stats["failed"] == 1
    job = db.execute(select(SyncJob)).scalars().one()
    assert job.status == "FAILED"
    assert job.attempts == 2
    assert job.finished_at is not None


def test_jobs_are_claimed_in_priority_order_and_only_when_due(db) -> None:
    service, _ = _prepared(db)
    service.match_links()
    widget_a = _product(db, "Widget A")
    _publishable_content(db, widget_a.id)
    service.enqueue_product_push([widget_a.id])
    service.enqueue_stock_sync(product_ids=[widget_a.id])

    future = db.execute(
        select(SyncJob).where(SyncJob.job_type == str(SyncJobType.SKYSHOP_PRODUCT_UPDATE))
    ).scalars().one()
    db.commit()

    claimed = claim_jobs(db, limit=10)
    assert [job.job_type for job in claimed] == [
        str(SyncJobType.SKYSHOP_STOCK_PUSH),
        str(SyncJobType.SKYSHOP_PRODUCT_UPDATE),
    ]
    assert all(job.status == str(SyncJobStatus.RUNNING) for job in claimed)
    assert all(job.attempts == 1 for job in claimed)

    future.status = str(SyncJobStatus.PENDING)
    future.next_attempt_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.commit()
    assert claim_jobs(db, limit=10) == []


def test_unknown_job_type_is_reported_not_silently_dropped(db) -> None:
    service, _ = _prepared(db)
    db.add(
        SyncJob(
            provider="SKYSHOP", job_type="SKYSHOP_TELEPORT", payload={},
            status=str(SyncJobStatus.PENDING), priority=5, max_attempts=1,
            next_attempt_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    assert process_pending_jobs(db, service=service)["failed"] == 1
    assert "Nieobsługiwany typ zadania" in (
        db.execute(select(SyncJob)).scalars().one().last_error
    )


@pytest.mark.parametrize(
    ("attempts", "expected_seconds"),
    [(1, 30), (2, 60), (3, 120), (10, 1800), (99, 1800)],
)
def test_backoff_grows_and_is_capped(attempts: int, expected_seconds: int) -> None:
    assert backoff_delay(attempts) == timedelta(seconds=expected_seconds)


def test_summary_reports_the_state_of_the_integration(db) -> None:
    service, _ = _prepared(db)
    service.match_links()
    service.enqueue_stock_sync()
    db.commit()

    summary = service.summary()
    assert summary["mirror_product_count"] == 2
    assert summary["link_status_counts"]["LINKED"] == 2
    assert summary["pending_jobs"] == 2
    assert summary["failed_jobs"] == 0
    assert summary["write_enabled"] is False  # off until an operator enables it
    assert summary["dry_run"] is True
    assert summary["stock_source"] == str(StockSource.LOCAL_LEDGER)
