"""SECURITY TESTS: the Fakturownia client must reject every write method.

These tests cover the acceptance criteria:
* the client blocks POST / PUT / PATCH / DELETE (and any other verb),
* the block happens at both the public-API layer and the transport layer,
* every blocked attempt triggers the audit callback,
* the API token never leaks into exception messages or logs.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.config import get_settings
from app.logging_config import mask_secrets
from app.services.fakturownia_client import (
    FakturowniaApiError,
    FakturowniaClient,
    FakturowniaReadOnlyViolation,
)

WRITE_METHODS = ["POST", "PUT", "PATCH", "DELETE"]


@pytest.fixture()
def audit_events() -> list[tuple[str, str, str]]:
    return []


@pytest.fixture()
def client(audit_events) -> FakturowniaClient:
    def audit_callback(method: str, url: str, description: str) -> None:
        audit_events.append((method, url, description))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    fk_client = FakturowniaClient(
        audit_callback=audit_callback,
        transport=httpx.MockTransport(handler),
    )
    yield fk_client
    fk_client.close()


@pytest.mark.parametrize("method", WRITE_METHODS)
def test_poison_methods_raise(client: FakturowniaClient, method: str, audit_events) -> None:
    poison = getattr(client, method.lower())
    with pytest.raises(FakturowniaReadOnlyViolation):
        poison("/invoices.json", json={"invoice": {"number": "X"}})
    assert audit_events, "read-only violation must be audited"
    assert audit_events[-1][0] == method


@pytest.mark.parametrize("method", WRITE_METHODS + ["HEAD", "OPTIONS", "TRACE"])
def test_generic_request_rejects_non_get(
    client: FakturowniaClient, method: str, audit_events
) -> None:
    with pytest.raises(FakturowniaReadOnlyViolation):
        client.request(method, "/products.json")
    assert audit_events[-1][0] == method.upper()


def test_transport_level_guard_blocks_write_even_bypassing_wrapper(
    client: FakturowniaClient, audit_events
) -> None:
    """Even direct use of the inner httpx client cannot send a write request."""
    inner: httpx.Client = client._client
    with pytest.raises(FakturowniaReadOnlyViolation):
        inner.post("/invoices.json", json={"invoice": {}})
    assert audit_events[-1][0] == "POST"


def test_get_is_allowed(client: FakturowniaClient) -> None:
    assert client.get("/products.json", {"page": 1}) == []


def test_get_sends_token_but_error_messages_are_masked() -> None:
    token = get_settings().fakturownia_api_token.get_secret_value()
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(404, text="not found")

    fk_client = FakturowniaClient(transport=httpx.MockTransport(handler))
    with pytest.raises(FakturowniaApiError) as exc_info:
        fk_client.get("/invoices/1.json")
    # Token must be in the actual request (Fakturownia requires it)...
    assert token in seen_urls[0]
    # ...but must never leak through exception text.
    assert token not in str(exc_info.value)
    fk_client.close()


def test_mask_secrets_masks_token_and_api_token_params() -> None:
    token = get_settings().fakturownia_api_token.get_secret_value()
    assert token not in mask_secrets(f"calling url?api_token={token}&page=1")
    assert token not in mask_secrets(f"raw secret in text: {token}")


def test_retry_with_backoff_on_server_errors(monkeypatch) -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json=[{"id": 1}])

    monkeypatch.setattr("time.sleep", lambda *_: None)
    fk_client = FakturowniaClient(transport=httpx.MockTransport(handler))
    assert fk_client.get("/products.json") == [{"id": 1}]
    assert attempts["count"] == 3
    fk_client.close()


def test_non_retryable_error_raises_immediately() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    fk_client = FakturowniaClient(transport=httpx.MockTransport(handler))
    with pytest.raises(FakturowniaApiError) as exc_info:
        fk_client.get("/products.json")
    assert exc_info.value.status_code == 401
    fk_client.close()


def test_pagination_iterates_until_short_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(dict(request.url.params)["page"])
        per_page = int(dict(request.url.params)["per_page"])
        if page == 1:
            return httpx.Response(200, json=[{"id": i} for i in range(per_page)])
        return httpx.Response(200, json=[{"id": 999}])

    fk_client = FakturowniaClient(transport=httpx.MockTransport(handler))
    pages = list(fk_client.iter_pages("/invoices.json"))
    assert len(pages) == 2
    assert len(pages[0]) == get_settings().fakturownia_per_page
    assert pages[1] == [{"id": 999}]
    fk_client.close()


def test_readonly_violation_is_persisted_to_audit_log(db) -> None:
    """End-to-end: violation -> audit_log row in the local database."""
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from app.audit.service import readonly_violation_audit_callback
    from app.models.audit import AuditLog

    session_factory = sessionmaker(bind=db.get_bind())
    fk_client = FakturowniaClient(
        audit_callback=readonly_violation_audit_callback(session_factory),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])),
    )
    with pytest.raises(FakturowniaReadOnlyViolation):
        fk_client.post("/clients.json", json={"client": {"name": "X"}})
    entries = db.execute(
        select(AuditLog).where(AuditLog.action == "READONLY_VIOLATION_BLOCKED")
    ).scalars().all()
    assert len(entries) == 1
    assert entries[0].object_id == "POST"
    fk_client.close()
