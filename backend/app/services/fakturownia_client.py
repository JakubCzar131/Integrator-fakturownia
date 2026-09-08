"""Read-only HTTP client for the Fakturownia API.

SECURITY CONTRACT
=================
This client is the *only* component allowed to talk to Fakturownia and it is
**hard-locked to HTTP GET**.  Any attempt to execute POST / PUT / PATCH /
DELETE (or any other verb) — whether through :meth:`request`, the convenience
methods, or the underlying ``httpx`` transport — raises
:class:`FakturowniaReadOnlyViolation` *before any network traffic happens*
and records an entry in the local audit log via the injected callback.

Defence in depth (three independent layers):

1. :meth:`request` validates the verb against the ``GET``-only allow-list.
2. The write verbs (``post``/``put``/``patch``/``delete``) exist only as
   poison methods that always raise.
3. An ``httpx`` request event hook re-checks every outgoing request at the
   transport level, so even code that bypasses this class and grabs the inner
   ``httpx.Client`` cannot send a write request.

The API token is sent as a query parameter (as required by Fakturownia) but is
never logged: URLs are masked through :func:`app.logging_config.mask_secrets`.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from app.logging_config import mask_secrets
from app.services.integration_config import (
    FakturowniaConfig,
    fakturownia_config_from_env,
)

logger = logging.getLogger(__name__)

ALLOWED_METHODS = frozenset({"GET"})

# Callback signature: (attempted_method, url, description) -> None
AuditCallback = Callable[[str, str, str], None]


class FakturowniaError(Exception):
    """Base error for Fakturownia client problems."""


class FakturowniaReadOnlyViolation(FakturowniaError):
    """Raised whenever a non-GET request towards Fakturownia is attempted."""

    def __init__(self, method: str, url: str = "") -> None:
        self.method = method
        self.url = mask_secrets(url)
        super().__init__(
            f"BLOCKED: attempted '{method}' request to Fakturownia. "
            "This system is hard-locked to read-only (GET) access. "
            "No write operation towards Fakturownia is ever permitted."
        )


class FakturowniaApiError(FakturowniaError):
    def __init__(self, status_code: int, url: str, body: str = "") -> None:
        self.status_code = status_code
        self.url = mask_secrets(url)
        super().__init__(
            f"Fakturownia API error {status_code} for {self.url}: {mask_secrets(body[:500])}"
        )


class _RateLimiter:
    """Simple thread-safe minimum-interval rate limiter."""

    def __init__(self, requests_per_second: float) -> None:
        self._min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._last_request = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            sleep_for = self._last_request + self._min_interval - now
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._last_request = time.monotonic()


class FakturowniaClient:
    """GET-only Fakturownia API client with retry, backoff and rate limiting."""

    RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        config: FakturowniaConfig | None = None,
        audit_callback: AuditCallback | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        # Configuration normally comes from the database (Ustawienia →
        # Integracje); the env-based config is the fallback.
        self._config = config or fakturownia_config_from_env()
        self._audit_callback = audit_callback
        self._rate_limiter = _RateLimiter(self._config.rate_limit_rps)
        self._client = httpx.Client(
            base_url=self._config.base_url,
            timeout=self._config.timeout_seconds,
            transport=transport,
            event_hooks={"request": [self._transport_guard]},
        )

    @property
    def config(self) -> FakturowniaConfig:
        return self._config

    # ------------------------------------------------------------------ #
    # Read-only guard
    # ------------------------------------------------------------------ #
    def _transport_guard(self, request: httpx.Request) -> None:
        """Last line of defence executed for *every* outgoing request."""
        if request.method.upper() not in ALLOWED_METHODS:
            self._record_violation(request.method, str(request.url))
            raise FakturowniaReadOnlyViolation(request.method, str(request.url))

    def _record_violation(self, method: str, url: str) -> None:
        masked_url = mask_secrets(url)
        logger.critical(
            "READ-ONLY GUARD: blocked %s request to Fakturownia (%s)", method, masked_url
        )
        if self._audit_callback is not None:
            try:
                self._audit_callback(
                    method,
                    masked_url,
                    f"Blocked forbidden '{method}' request to Fakturownia (read-only guard)",
                )
            except Exception:  # pragma: no cover - auditing must not mask the violation
                logger.exception("Failed to write read-only violation to audit log")

    def request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        """Execute a request. Only GET is permitted — everything else raises."""
        method_upper = (method or "").upper()
        if method_upper not in ALLOWED_METHODS:
            self._record_violation(method_upper, f"{self._config.base_url}{path}")
            raise FakturowniaReadOnlyViolation(method_upper, path)
        return self._get_with_retry(path, params or {})

    # Poison methods: they exist so that even a habitual `client.post(...)`
    # call fails loudly instead of silently doing nothing.
    def post(self, path: str, *args: Any, **kwargs: Any) -> Any:
        self._record_violation("POST", path)
        raise FakturowniaReadOnlyViolation("POST", path)

    def put(self, path: str, *args: Any, **kwargs: Any) -> Any:
        self._record_violation("PUT", path)
        raise FakturowniaReadOnlyViolation("PUT", path)

    def patch(self, path: str, *args: Any, **kwargs: Any) -> Any:
        self._record_violation("PATCH", path)
        raise FakturowniaReadOnlyViolation("PATCH", path)

    def delete(self, path: str, *args: Any, **kwargs: Any) -> Any:
        self._record_violation("DELETE", path)
        raise FakturowniaReadOnlyViolation("DELETE", path)

    # ------------------------------------------------------------------ #
    # GET implementation with retry / backoff / rate limiting
    # ------------------------------------------------------------------ #
    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params)

    def _get_with_retry(self, path: str, params: dict[str, Any]) -> Any:
        query = dict(params)
        query["api_token"] = self._config.api_token

        last_error: Exception | None = None
        for attempt in range(1, self._config.max_retries + 1):
            self._rate_limiter.wait()
            try:
                response = self._client.get(path, params=query)
            except FakturowniaReadOnlyViolation:
                raise
            except httpx.HTTPError as exc:
                last_error = FakturowniaError(
                    f"Network error calling Fakturownia {path}: {mask_secrets(str(exc))}"
                )
                logger.warning(
                    "Fakturownia GET %s failed (attempt %d/%d): %s",
                    path, attempt, self._config.max_retries,
                    mask_secrets(str(exc)),
                )
                self._sleep_backoff(attempt)
                continue

            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as exc:
                    raise FakturowniaApiError(
                        response.status_code, str(response.url), "Invalid JSON response"
                    ) from exc

            if response.status_code in self.RETRYABLE_STATUS_CODES:
                last_error = FakturowniaApiError(
                    response.status_code, str(response.url), response.text
                )
                logger.warning(
                    "Fakturownia GET %s returned %d (attempt %d/%d)",
                    path, response.status_code, attempt,
                    self._config.max_retries,
                )
                self._sleep_backoff(attempt, response)
                continue

            raise FakturowniaApiError(response.status_code, str(response.url), response.text)

        raise last_error or FakturowniaError(f"Fakturownia GET {path} failed after retries")

    def _sleep_backoff(self, attempt: int, response: httpx.Response | None = None) -> None:
        delay = min(2 ** attempt, 60)
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = max(delay, int(retry_after))
        time.sleep(delay)

    # ------------------------------------------------------------------ #
    # Pagination helper + typed resource accessors (all GET)
    # ------------------------------------------------------------------ #
    def iter_pages(
        self, path: str, params: dict[str, Any] | None = None, per_page: int | None = None
    ) -> Iterator[list[dict[str, Any]]]:
        """Iterate over all pages of a paginated list endpoint."""
        per_page = per_page or self._config.per_page
        page = 1
        while True:
            page_params = dict(params or {})
            page_params.update({"page": page, "per_page": per_page})
            data = self.get(path, page_params)
            if not isinstance(data, list):
                # Some endpoints wrap results; normalize to a list.
                data = data.get("data", []) if isinstance(data, dict) else []
            if not data:
                return
            yield data
            if len(data) < per_page:
                return
            page += 1

    def iter_invoices(self, period: str = "all", **extra: Any) -> Iterator[list[dict[str, Any]]]:
        params: dict[str, Any] = {"period": period, "include_positions": "true"}
        params.update(extra)
        return self.iter_pages("/invoices.json", params)

    def get_invoice(self, invoice_id: int) -> dict[str, Any]:
        return self.get(f"/invoices/{invoice_id}.json")

    def iter_products(self, warehouse_id: int | None = None) -> Iterator[list[dict[str, Any]]]:
        params: dict[str, Any] = {}
        if warehouse_id is not None:
            params["warehouse_id"] = warehouse_id
        return self.iter_pages("/products.json", params)

    def iter_clients(self) -> Iterator[list[dict[str, Any]]]:
        return self.iter_pages("/clients.json")

    def get_warehouses(self) -> list[dict[str, Any]]:
        data = self.get("/warehouses.json")
        return data if isinstance(data, list) else []

    def iter_warehouse_documents(self) -> Iterator[list[dict[str, Any]]]:
        return self.iter_pages("/warehouse_documents.json")

    def iter_warehouse_actions(self) -> Iterator[list[dict[str, Any]]]:
        return self.iter_pages("/warehouse_actions.json")

    def get_categories(self) -> list[dict[str, Any]]:
        data = self.get("/categories.json")
        return data if isinstance(data, list) else []

    def get_departments(self) -> list[dict[str, Any]]:
        data = self.get("/departments.json")
        return data if isinstance(data, list) else []

    def iter_payments(self) -> Iterator[list[dict[str, Any]]]:
        return self.iter_pages("/banking/payments.json", {"include": "invoices"})

    def get_price_lists(self) -> list[dict[str, Any]]:
        data = self.get("/price_lists.json")
        return data if isinstance(data, list) else []

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FakturowniaClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()
