"""SkyShop HTTP surface: links, mirror, categories, PIM content and the queue."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.models.product import Product
from app.models.skyshop import SkyShopCategory, SkyShopProduct, SkyShopProductLink
from app.models.sync import SyncJob
from app.services.sync_service import SyncService
from app.tests.fixtures import FakeFakturowniaClient


def _seed(db) -> None:
    """Fakturownia data plus a hand-built shop mirror (no API traffic in tests)."""
    SyncService(db, FakeFakturowniaClient()).run_full_sync()
    db.add_all([
        SkyShopProduct(
            skyshop_id="S-1", sku="WID-A", ean="5901234567890", name="Widget A",
            price_gross=Decimal("123.00"), quantity=Decimal("40"),
            category_skyshop_id="C-10", is_active=True,
        ),
        SkyShopProduct(
            skyshop_id="S-2", sku="OBCY-KOD", name="Produkt tylko w sklepie",
            quantity=Decimal("3"),
        ),
        SkyShopCategory(skyshop_id="C-10", name="Elektronika", path="Elektronika"),
    ])
    db.commit()


def _product_id(db, name: str) -> int:
    return db.execute(select(Product).where(Product.name == name)).scalar_one().id


def test_summary_describes_the_integration_state(client, admin_headers, seeded_db) -> None:
    _seed(seeded_db)
    summary = client.get("/api/v1/skyshop/summary", headers=admin_headers).json()
    assert summary["mirror_product_count"] == 2
    # Writes stay off and dry-run stays on until an operator decides otherwise.
    assert summary["write_enabled"] is False
    assert summary["dry_run"] is True
    assert summary["pending_jobs"] == 0


def test_matching_then_listing_shows_link_and_stock_state(
    client, admin_headers, seeded_db
) -> None:
    _seed(seeded_db)
    matched = client.post("/api/v1/skyshop/links/match", headers=admin_headers)
    assert matched.status_code == 200, matched.text
    assert matched.json()["detail"]["linked"] == 1

    links = {
        item["product_name"]: item
        for item in client.get("/api/v1/skyshop/links", headers=admin_headers).json()["items"]
    }
    widget_a = links["Widget A"]
    assert widget_a["status"] == "LINKED"
    assert widget_a["match_type"] == "SKU"
    assert widget_a["shop_name"] == "Widget A"
    assert Decimal(widget_a["shop_stock"]) == Decimal("40")
    assert Decimal(widget_a["local_stock"]) == Decimal("-8")
    # Never pushed anything yet, so both fingerprints are out of date.
    assert widget_a["stock_out_of_sync"] is True
    assert widget_a["content_out_of_sync"] is True

    assert links["Widget B"]["status"] == "MISSING"
    assert links["Widget B"]["shop_stock"] is None

    filtered = client.get(
        "/api/v1/skyshop/links?status=MISSING", headers=admin_headers
    ).json()
    assert [item["product_name"] for item in filtered["items"]] == ["Widget B"]


def test_operator_can_link_manually_and_exclude_a_product(
    client, admin_headers, seeded_db
) -> None:
    _seed(seeded_db)
    widget_b = _product_id(seeded_db, "Widget B")

    linked = client.patch(
        f"/api/v1/skyshop/links/{widget_b}",
        json={"skyshop_id": "S-2", "notes": "ustalone z obsługą sklepu"},
        headers=admin_headers,
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["status"] == "LINKED"
    assert linked.json()["match_type"] == "MANUAL"

    excluded = client.patch(
        f"/api/v1/skyshop/links/{widget_b}",
        json={"status": "EXCLUDED"},
        headers=admin_headers,
    )
    assert excluded.json()["status"] == "EXCLUDED"

    assert client.patch(
        "/api/v1/skyshop/links/9999", json={"status": "EXCLUDED"}, headers=admin_headers
    ).status_code == 404


def test_mirror_listing_can_isolate_products_missing_locally(
    client, admin_headers, seeded_db
) -> None:
    _seed(seeded_db)
    client.post("/api/v1/skyshop/links/match", headers=admin_headers)
    unlinked = client.get(
        "/api/v1/skyshop/products?only_unlinked=true", headers=admin_headers
    ).json()
    assert [item["skyshop_id"] for item in unlinked["items"]] == ["S-2"]


def test_mirror_refresh_reports_a_missing_configuration_clearly(
    client, admin_headers, seeded_db
) -> None:
    _seed(seeded_db)
    response = client.post("/api/v1/skyshop/mirror/refresh", headers=admin_headers)
    assert response.status_code == 400
    assert "Ustawienia" in response.json()["detail"]


def test_mirror_refresh_can_be_deferred_to_the_queue(client, admin_headers, seeded_db) -> None:
    _seed(seeded_db)
    response = client.post(
        "/api/v1/skyshop/mirror/refresh?background=true", headers=admin_headers
    )
    assert response.status_code == 200
    job = seeded_db.execute(select(SyncJob)).scalars().one()
    assert job.job_type == "SKYSHOP_MIRROR_REFRESH"
    assert job.dedupe_key == "mirror:refresh"


def test_category_mappings_are_upserted_and_removable(client, admin_headers, seeded_db) -> None:
    _seed(seeded_db)
    created = client.put(
        "/api/v1/skyshop/category-mappings",
        json={"local_category": "Elektronika", "skyshop_category_id": "C-10"},
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    mapping_id = created.json()["id"]

    updated = client.put(
        "/api/v1/skyshop/category-mappings",
        json={"local_category": "Elektronika", "skyshop_category_id": "C-20"},
        headers=admin_headers,
    )
    assert updated.json()["id"] == mapping_id  # upsert, not a duplicate
    assert updated.json()["skyshop_category_id"] == "C-20"

    categories = client.get("/api/v1/skyshop/categories", headers=admin_headers).json()
    assert categories[0]["skyshop_id"] == "C-10"

    listed = client.get("/api/v1/skyshop/category-mappings", headers=admin_headers).json()
    assert listed[0]["local_category"] == "Elektronika"

    assert client.delete(
        f"/api/v1/skyshop/category-mappings/{mapping_id}", headers=admin_headers
    ).status_code == 200
    assert client.get(
        "/api/v1/skyshop/category-mappings", headers=admin_headers
    ).json() == []


def test_pim_content_is_editable_and_reports_publication_problems(
    client, admin_headers, seeded_db
) -> None:
    _seed(seeded_db)
    widget_a = _product_id(seeded_db, "Widget A")

    empty = client.get(f"/api/v1/products/{widget_a}/content", headers=admin_headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["publication_problems"]

    saved = client.put(
        f"/api/v1/products/{widget_a}/content",
        json={
            "short_description": "Solidny widget",
            "description_html": "<p>Opis</p>",
            "price_gross": "123.00",
            "vat_rate": "23",
            "local_category": "Elektronika",
            "attributes": {"Kolor": "czerwony"},
            "images": [{"url": "https://example.pl/a.jpg", "position": 1}],
        },
        headers=admin_headers,
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["attributes"] == {"Kolor": "czerwony"}
    assert body["content_hash"]
    # The category still has no shop counterpart, so publication stays blocked.
    assert any("nie jest zmapowana" in problem for problem in body["publication_problems"])

    client.put(
        "/api/v1/skyshop/category-mappings",
        json={"local_category": "Elektronika", "skyshop_category_id": "C-10"},
        headers=admin_headers,
    )
    ready = client.get(f"/api/v1/products/{widget_a}/content", headers=admin_headers).json()
    assert ready["publication_problems"] == []


def test_push_is_refused_for_products_that_are_not_ready(
    client, admin_headers, seeded_db
) -> None:
    _seed(seeded_db)
    widget_a = _product_id(seeded_db, "Widget A")
    response = client.post(
        "/api/v1/skyshop/products/push",
        json={"product_ids": [widget_a]},
        headers=admin_headers,
    )
    assert response.status_code == 200
    detail = response.json()["detail"]
    assert detail["enqueued"] == 0
    assert detail["rejected"][0]["problems"]
    assert seeded_db.execute(select(SyncJob)).scalars().all() == []


def test_stock_sync_queues_only_linked_products(client, admin_headers, seeded_db) -> None:
    _seed(seeded_db)
    client.post("/api/v1/skyshop/links/match", headers=admin_headers)
    response = client.post(
        "/api/v1/skyshop/stock/sync", json={"force": False}, headers=admin_headers
    )
    assert response.status_code == 200
    assert response.json()["detail"] == {"considered": 1, "enqueued": 1, "unchanged": 0}

    jobs = client.get("/api/v1/skyshop/jobs", headers=admin_headers).json()
    assert jobs["total"] == 1
    assert jobs["items"][0]["job_type"] == "SKYSHOP_STOCK_PUSH"
    assert jobs["items"][0]["product_name"] == "Widget A"
    assert jobs["items"][0]["status"] == "PENDING"


def test_dead_lettered_jobs_can_be_retried_or_cancelled(
    client, admin_headers, seeded_db
) -> None:
    _seed(seeded_db)
    client.post("/api/v1/skyshop/links/match", headers=admin_headers)
    client.post("/api/v1/skyshop/stock/sync", json={}, headers=admin_headers)
    job = seeded_db.execute(select(SyncJob)).scalars().one()
    job.status = "FAILED"
    job.attempts = 5
    job.last_error = "sklep nieosiągalny"
    seeded_db.commit()

    retried = client.post(f"/api/v1/skyshop/jobs/{job.id}/retry", headers=admin_headers)
    assert retried.status_code == 200
    seeded_db.expire_all()
    job = seeded_db.get(SyncJob, job.id)
    assert (job.status, job.attempts, job.last_error) == ("PENDING", 0, None)

    cancelled = client.post(f"/api/v1/skyshop/jobs/{job.id}/cancel", headers=admin_headers)
    assert cancelled.status_code == 200
    seeded_db.expire_all()
    assert seeded_db.get(SyncJob, job.id).status == "CANCELLED"

    # A completed job must not be rewritten into a cancelled one.
    job.status = "SUCCESS"
    seeded_db.commit()
    assert client.post(
        f"/api/v1/skyshop/jobs/{job.id}/cancel", headers=admin_headers
    ).status_code == 409

    assert client.post(
        "/api/v1/skyshop/jobs/999/retry", headers=admin_headers
    ).status_code == 404


def test_endpoints_require_authentication(client) -> None:
    assert client.get("/api/v1/skyshop/summary").status_code == 401
    assert client.get("/api/v1/skyshop/links").status_code == 401
    assert client.post("/api/v1/skyshop/links/match").status_code == 401
    assert client.post(
        "/api/v1/skyshop/products/push", json={"product_ids": [1]}
    ).status_code == 401
    assert client.post("/api/v1/skyshop/stock/sync", json={}).status_code == 401
