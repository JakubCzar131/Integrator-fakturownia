"""HTTP client for the SkyShop WebAPI (the only outbound *write* direction).

SECURITY CONTRACT
=================
This class is physically separate from :class:`
app.services.fakturownia_client.FakturowniaClient`, which stays hard-locked to
GET.  There is no shared code path, so a write can never be routed towards
Fakturownia by mistake.

Safety mechanisms around every mutation:

* **kill switch** — ``skyshop_sync_enabled`` (app_settings).  When off, writes
  raise :class:`SkyShopWriteBlocked` before any network traffic.
* **dry-run** — ``skyshop_dry_run``.  The full payload is built and logged, the
  request is *not* sent, and the caller receives ``{"dry_run": true, ...}``.
* **audit** — every attempted mutation goes through the injected callback, so
  the local audit log holds the payload and the response.
* **rate limiting** — SkyShop allows one request per second; the limiter is
  built into the client, not into the callers, so no code path can bypass it.

The concrete resource paths differ slightly between shops (each shop serves its
own documentation under ``https://{domain}/api``), so paths are kept in
:class:`SkyShopEndpoints` and can be overridden per account in the integration
configuration without touching this module.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.logging_config import mask_secrets, register_secret
from app.services.integration_config import SkyShopConfig

logger = logging.getLogger(__name__)

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Callback signature: (action, method, path, payload, response, blocked_reason)
AuditCallback = Any


class SkyShopError(Exception):
    """Base error for SkyShop client problems."""


class SkyShopNotConfigured(SkyShopError):
    def __init__(self) -> None:
        super().__init__(
            "Integracja SkyShop nie jest skonfigurowana — dodaj konto w "
            "Ustawienia → Integracje (adres sklepu + klucz WebAPI)."
        )


class SkyShopWriteBlocked(SkyShopError):
    """Raised when a mutation is attempted while the kill switch is off."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Zapis do SkyShop zablokowany: {reason}")


class SkyShopApiError(SkyShopError):
    def __init__(self, status_code: int, url: str, body: str = "") -> None:
        self.status_code = status_code
        self.url = mask_secrets(url)
        super().__init__(
            f"SkyShop API error {status_code} for {self.url}: {mask_secrets(body[:500])}"
        )


@dataclass(frozen=True)
class SkyShopEndpoints:
    """Resource paths, overridable per shop through the account config."""

    products: str = "/products"
    product: str = "/products/{id}"
    categories: str = "/categories"
    stock: str = "/products/{id}/stock"
    stock_bulk: str = "/products/stock"
    ping: str = "/status"

    @classmethod
    def from_config(cls, extra: dict[str, Any] | None) -> "SkyShopEndpoints":
        overrides = (extra or {}).get("endpoints") or {}
        known = {f: overrides[f] for f in cls.__dataclass_fields__ if f in overrides}
        return cls(**known)


class _RateLimiter:
    """Thread-safe minimum-interval limiter (SkyShop hard limit: 1 rps)."""

    def __init__(self, requests_per_second: float) -> None:
        self._min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._last_request = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            sleep_for = self._last_request + self._min_interval - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._last_request = time.monotonic()


class SkyShopClient:
    """SkyShop WebAPI client: reads freely, writes only when explicitly enabled."""

    RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        config: SkyShopConfig,
        *,
        write_enabled: bool = False,
        dry_run: bool = True,
        audit_callback: AuditCallback | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not config.is_configured:
            raise SkyShopNotConfigured()
        self._config = config
        self._write_enabled = write_enabled
        self._dry_run = dry_run
        self._audit_callback = audit_callback
        self._endpoints = SkyShopEndpoints.from_config(config.extra)
        self._rate_limiter = _RateLimiter(config.rate_limit_rps)
        register_secret(config.api_key)
        self._client = httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            transport=transport,
            headers={
                "Accept": "application/json",
                # Shops accept the WebAPI key either as a header or as a query
                # parameter; both are sent so a single adapter fits both setups.
                "X-Api-Key": config.api_key,
                "Authorization": f"Bearer {config.api_key}",
            },
        )

    # ------------------------------------------------------------------ #
    # Properties
    # ------------------------------------------------------------------ #
    @property
    def endpoints(self) -> SkyShopEndpoints:
        return self._endpoints

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    @property
    def write_enabled(self) -> bool:
        return self._write_enabled

    @property
    def config(self) -> SkyShopConfig:
        return self._config

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def iter_pages(
        self, path: str, params: dict[str, Any] | None = None, per_page: int = 100
    ) -> Any:
        """Iterate a paginated collection, tolerating the common envelope shapes."""
        page = 1
        while True:
            payload = self.get(path, {**(params or {}), "page": page, "limit": per_page})
            items = _extract_items(payload)
            if not items:
                return
            yield items
            if len(items) < per_page:
                return
            page += 1

    def ping(self) -> Any:
        """Lightweight read used by the connection test."""
        try:
            return self.get(self._endpoints.ping)
        except SkyShopApiError as exc:
            # Not every shop exposes /status; a reachable product list is
            # equally good proof that the key works.
            if exc.status_code != 404:
                raise
            return self.get(self._endpoints.products, {"page": 1, "limit": 1})

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def write(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
        *,
        action: str = "SKYSHOP_WRITE",
    ) -> dict[str, Any]:
        """Perform a guarded mutation. Returns the parsed response or dry-run echo."""
        method_upper = method.upper()
        if method_upper not in WRITE_METHODS:
            raise SkyShopError(f"{method_upper} nie jest operacją zapisu")
        if not self._write_enabled:
            self._audit(action, method_upper, path, payload, None,
                        blocked_reason="kill switch skyshop_sync_enabled = false")
            raise SkyShopWriteBlocked(
                "wyłączony globalny przełącznik skyshop_sync_enabled"
            )
        if self._dry_run:
            logger.info(
                "SkyShop DRY-RUN %s %s payload=%s",
                method_upper, path, mask_secrets(str(payload)),
            )
            self._audit(action, method_upper, path, payload, {"dry_run": True})
            return {"dry_run": True, "method": method_upper, "path": path, "payload": payload}

        response = self._request(method_upper, path, json=payload)
        self._audit(action, method_upper, path, payload, response)
        return response if isinstance(response, dict) else {"result": response}

    def post(self, path: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return self.write("POST", path, payload, **kwargs)

    def put(self, path: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return self.write("PUT", path, payload, **kwargs)

    # ------------------------------------------------------------------ #
    # Transport
    # ------------------------------------------------------------------ #
    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        query = dict(params or {})
        query.setdefault("api_key", self._config.api_key)
        last_error: Exception | None = None

        for attempt in range(1, self._config.max_retries + 1):
            self._rate_limiter.wait()
            try:
                response = self._client.request(method, path, params=query, json=json)
            except httpx.HTTPError as exc:
                last_error = SkyShopError(
                    f"Błąd sieci przy {method} {path}: {mask_secrets(str(exc))}"
                )
                logger.warning(
                    "SkyShop %s %s failed (attempt %d/%d): %s",
                    method, path, attempt, self._config.max_retries, mask_secrets(str(exc)),
                )
                self._sleep_backoff(attempt)
                continue

            if 200 <= response.status_code < 300:
                if not response.content:
                    return {}
                try:
                    return response.json()
                except ValueError as exc:
                    raise SkyShopApiError(
                        response.status_code, str(response.url), "Nieprawidłowy JSON"
                    ) from exc

            if response.status_code in self.RETRYABLE_STATUS_CODES:
                last_error = SkyShopApiError(
                    response.status_code, str(response.url), response.text
                )
                logger.warning(
                    "SkyShop %s %s returned %d (attempt %d/%d)",
                    method, path, response.status_code, attempt, self._config.max_retries,
                )
                self._sleep_backoff(attempt, response)
                continue

            raise SkyShopApiError(response.status_code, str(response.url), response.text)

        raise last_error or SkyShopError(f"SkyShop {method} {path} nie powiodło się")

    def _sleep_backoff(self, attempt: int, response: httpx.Response | None = None) -> None:
        delay = min(2 ** attempt, 60)
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = max(delay, int(retry_after))
        time.sleep(delay)

    def _audit(
        self,
        action: str,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        response: Any,
        blocked_reason: str | None = None,
    ) -> None:
        if self._audit_callback is None:
            return
        try:
            self._audit_callback(action, method, path, payload, response, blocked_reason)
        except Exception:  # pragma: no cover - auditing must never break a write
            logger.exception("Nie udało się zapisać audytu operacji SkyShop")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SkyShopClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    """Normalize the response envelopes seen across SkyShop deployments."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "items", "products", "categories", "results", "list"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if isinstance(payload.get("data"), dict):
            return _extract_items(payload["data"])
    return []
