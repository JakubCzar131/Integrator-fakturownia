"""In-memory SkyShop WebAPI used by the integration tests.

The fake records every request so tests can assert not only *what* was sent
but also that guarded paths sent nothing at all.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.models.enums import ConfigSource
from app.services.integration_config import SkyShopConfig
from app.services.skyshop_client import SkyShopClient

SHOP_BASE_URL = "https://sklep.example.pl/api"
SHOP_API_KEY = "skyshop-webapi-key-1234"

SHOP_PRODUCTS = [
    {"id": "S-1", "sku": "WID-A", "ean": "5901234567890", "name": "Widget A",
     "price_gross": "123.00", "quantity": "40", "category_id": "C-10", "active": True},
    {"id": "S-2", "sku": "WID-B", "ean": None, "name": "Widget B",
     "price_gross": "12.30", "quantity": "5", "category_id": "C-10", "active": True},
]

SHOP_CATEGORIES = [
    {"id": "C-10", "name": "Elektronika", "parent_id": None, "path": "Elektronika"},
    {"id": "C-20", "name": "Akcesoria", "parent_id": "C-10", "path": "Elektronika/Akcesoria"},
]


@dataclass
class RecordedRequest:
    method: str
    path: str
    body: dict[str, Any] | None
    params: dict[str, str]


@dataclass
class FakeShop:
    """Configurable stand-in for a shop's WebAPI."""

    products: list[dict[str, Any]] = field(default_factory=lambda: list(SHOP_PRODUCTS))
    categories: list[dict[str, Any]] = field(default_factory=lambda: list(SHOP_CATEGORIES))
    requests: list[RecordedRequest] = field(default_factory=list)
    # Status codes returned before the request is allowed to succeed.
    failures: list[int] = field(default_factory=list)
    envelope: str | None = "data"
    created_product_id: str = "S-99"

    @property
    def writes(self) -> list[RecordedRequest]:
        return [r for r in self.requests if r.method != "GET"]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _wrap(self, items: list[dict[str, Any]]) -> Any:
        return {self.envelope: items} if self.envelope else items

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append(
            RecordedRequest(
                method=request.method,
                path=request.url.path,
                body=body,
                params=dict(request.url.params),
            )
        )
        if self.failures:
            return httpx.Response(self.failures.pop(0), json={"error": "chwilowy błąd"})

        path = request.url.path
        page = int(request.url.params.get("page", 1))
        if request.method == "GET":
            if path.endswith("/products"):
                return httpx.Response(200, json=self._wrap(self.products if page == 1 else []))
            if path.endswith("/categories"):
                return httpx.Response(200, json=self._wrap(self.categories if page == 1 else []))
            if path.endswith("/status"):
                return httpx.Response(200, json={"status": "ok"})
            return httpx.Response(404, json={"error": "nie znaleziono"})
        if request.method == "POST" and path.endswith("/products"):
            return httpx.Response(201, json={"id": self.created_product_id, **(body or {})})
        return httpx.Response(200, json={"ok": True})


def shop_config(**overrides: Any) -> SkyShopConfig:
    params: dict[str, Any] = {
        "base_url": SHOP_BASE_URL,
        "api_key": SHOP_API_KEY,
        # Tests must not pay the platform's one-request-per-second penance.
        "rate_limit_rps": 0,
        "max_retries": 3,
        "source": ConfigSource.ENV,
        "label": "Sklep testowy",
    }
    params.update(overrides)
    return SkyShopConfig(**params)


def make_client(
    shop: FakeShop | None = None,
    *,
    write_enabled: bool = True,
    dry_run: bool = False,
    audit_callback: Any = None,
    config: SkyShopConfig | None = None,
) -> tuple[SkyShopClient, FakeShop]:
    shop = shop or FakeShop()
    client = SkyShopClient(
        config or shop_config(),
        write_enabled=write_enabled,
        dry_run=dry_run,
        audit_callback=audit_callback,
        transport=shop.transport(),
    )
    return client, shop
