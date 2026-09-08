"""SkyShop client safety contract: kill switch, dry-run, audit, retries, limits."""
from __future__ import annotations

import time

import httpx
import pytest

from app.logging_config import mask_secrets
from app.services import skyshop_client as client_module
from app.services.skyshop_client import (
    SkyShopApiError,
    SkyShopClient,
    SkyShopEndpoints,
    SkyShopError,
    SkyShopNotConfigured,
    SkyShopWriteBlocked,
    _extract_items,
)
from app.tests.skyshop_fixtures import (
    SHOP_API_KEY,
    FakeShop,
    make_client,
    shop_config,
)


@pytest.fixture()
def audit_log() -> list[tuple]:
    return []


@pytest.fixture()
def no_sleep(monkeypatch) -> None:
    """Retries must be exercised without waiting out the real backoff."""
    monkeypatch.setattr(client_module.time, "sleep", lambda _seconds: None)


def test_unconfigured_account_is_refused_before_any_traffic() -> None:
    with pytest.raises(SkyShopNotConfigured):
        SkyShopClient(shop_config(api_key=""))


def test_reads_do_not_require_the_kill_switch() -> None:
    client, shop = make_client(write_enabled=False)
    with client:
        assert client.get("/status") == {"status": "ok"}
    assert [request.method for request in shop.requests] == ["GET"]


def test_kill_switch_blocks_the_write_and_audits_the_attempt(audit_log) -> None:
    client, shop = make_client(write_enabled=False, audit_callback=_recorder(audit_log))
    with client, pytest.raises(SkyShopWriteBlocked) as exc:
        client.post("/products", {"name": "Nowy produkt"})

    assert "skyshop_sync_enabled" in str(exc.value)
    assert shop.writes == []  # nothing left the process
    action, method, path, payload, response, blocked = audit_log[0]
    assert (action, method, path) == ("SKYSHOP_WRITE", "POST", "/products")
    assert payload == {"name": "Nowy produkt"}
    assert response is None
    assert "kill switch" in blocked


def test_dry_run_builds_the_payload_without_sending_it(audit_log) -> None:
    client, shop = make_client(dry_run=True, audit_callback=_recorder(audit_log))
    with client:
        result = client.put("/products/S-1", {"quantity": "7"})

    assert result == {
        "dry_run": True, "method": "PUT", "path": "/products/S-1",
        "payload": {"quantity": "7"},
    }
    assert shop.writes == []
    assert audit_log[0][4] == {"dry_run": True}
    assert audit_log[0][5] is None  # a dry run is not a blocked write


def test_enabled_write_reaches_the_shop_and_is_audited(audit_log) -> None:
    client, shop = make_client(audit_callback=_recorder(audit_log))
    with client:
        response = client.post("/products", {"name": "Nowy produkt"})

    assert response["id"] == "S-99"
    assert [(r.method, r.path) for r in shop.writes] == [("POST", "/api/products")]
    assert shop.writes[0].body == {"name": "Nowy produkt"}
    assert len(audit_log) == 1
    assert audit_log[0][4]["id"] == "S-99"


def test_get_is_rejected_as_a_write_operation() -> None:
    client, shop = make_client()
    with client, pytest.raises(SkyShopError, match="nie jest operacją zapisu"):
        client.write("GET", "/products", {})
    assert shop.requests == []


def test_auditing_failure_never_breaks_a_write() -> None:
    def exploding_callback(*_args) -> None:
        raise RuntimeError("audyt niedostępny")

    client, shop = make_client(audit_callback=exploding_callback)
    with client:
        assert client.post("/products", {"name": "X"})["id"] == "S-99"
    assert len(shop.writes) == 1


@pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
def test_transient_failures_are_retried(status_code: int, no_sleep) -> None:
    shop = FakeShop(failures=[status_code])
    client, _ = make_client(shop)
    with client:
        assert client.get("/status") == {"status": "ok"}
    assert len(shop.requests) == 2


def test_retries_are_bounded_by_max_retries(no_sleep) -> None:
    shop = FakeShop(failures=[503, 503, 503, 503, 503])
    client, _ = make_client(shop, config=shop_config(max_retries=3))
    with client, pytest.raises(SkyShopApiError):
        client.get("/status")
    assert len(shop.requests) == 3


def test_client_errors_are_not_retried(no_sleep) -> None:
    shop = FakeShop(failures=[422])
    client, _ = make_client(shop)
    with client, pytest.raises(SkyShopApiError) as exc:
        client.post("/products", {"name": "X"})
    assert exc.value.status_code == 422
    assert len(shop.requests) == 1


def test_retry_after_header_is_respected(monkeypatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", slept.append)

    def handler(request: httpx.Request) -> httpx.Response:
        if len(slept) == 0:
            return httpx.Response(429, headers={"Retry-After": "45"}, json={})
        return httpx.Response(200, json={"status": "ok"})

    client = SkyShopClient(
        shop_config(), write_enabled=True, dry_run=False,
        transport=httpx.MockTransport(handler),
    )
    with client:
        assert client.get("/status") == {"status": "ok"}
    assert slept == [45]


def test_network_errors_are_retried_then_reported(no_sleep) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sklep nieosiągalny")

    client = SkyShopClient(
        shop_config(max_retries=2), write_enabled=True, dry_run=False,
        transport=httpx.MockTransport(handler),
    )
    with client, pytest.raises(SkyShopError, match="Błąd sieci"):
        client.get("/status")


def test_api_key_is_masked_in_errors_and_logs() -> None:
    shop = FakeShop(failures=[422])
    client, _ = make_client(shop)
    with client, pytest.raises(SkyShopApiError) as exc:
        client.post("/products", {"name": "X"})
    # The key travels as a query parameter, so it must not survive into the message.
    assert SHOP_API_KEY not in str(exc.value)
    assert SHOP_API_KEY not in mask_secrets(f"klucz {SHOP_API_KEY}")


def test_rate_limiter_enforces_the_platform_interval() -> None:
    shop = FakeShop()
    client, _ = make_client(shop, config=shop_config(rate_limit_rps=20))
    started = time.monotonic()
    with client:
        for _ in range(3):
            client.get("/status")
    # Two gaps of 50 ms between three requests; measured loosely on purpose.
    assert time.monotonic() - started >= 0.09
    assert len(shop.requests) == 3


def test_pagination_stops_when_a_page_is_short() -> None:
    shop = FakeShop()
    client, _ = make_client(shop)
    with client:
        pages = list(client.iter_pages("/products", per_page=100))
    assert [len(page) for page in pages] == [2]
    assert len(shop.requests) == 1


def test_ping_falls_back_to_the_product_list_when_status_is_absent() -> None:
    shop = FakeShop()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/status"):
            return httpx.Response(404, json={"error": "brak"})
        return httpx.Response(200, json={"data": shop.products})

    client = SkyShopClient(
        shop_config(), write_enabled=False, dry_run=True,
        transport=httpx.MockTransport(handler),
    )
    with client:
        assert client.ping()["data"]


@pytest.mark.parametrize(
    "payload",
    [
        [{"id": "1"}],
        {"data": [{"id": "1"}]},
        {"items": [{"id": "1"}]},
        {"products": [{"id": "1"}]},
        {"results": [{"id": "1"}]},
        {"data": {"products": [{"id": "1"}]}},
    ],
)
def test_response_envelopes_are_normalized(payload) -> None:
    assert _extract_items(payload) == [{"id": "1"}]


@pytest.mark.parametrize("payload", [None, {}, {"data": None}, "tekst", 7])
def test_unknown_envelopes_yield_no_items(payload) -> None:
    assert _extract_items(payload) == []


def test_endpoint_paths_can_be_overridden_per_shop() -> None:
    endpoints = SkyShopEndpoints.from_config(
        {"endpoints": {"products": "/catalog/items", "nieznane": "/x"}}
    )
    assert endpoints.products == "/catalog/items"
    assert endpoints.stock == SkyShopEndpoints().stock  # untouched default


def _recorder(sink: list[tuple]):
    def callback(*args) -> None:
        sink.append(args)

    return callback
