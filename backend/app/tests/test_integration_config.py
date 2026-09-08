"""Integration accounts: encryption, DB→env precedence, and secret non-disclosure."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.logging_config import mask_secrets
from app.models.audit import AuditLog
from app.models.enums import ConfigSource, IntegrationProvider
from app.models.integration import IntegrationAccount
from app.security.crypto import decrypt_secret, encrypt_secret, secret_hint
from app.services.integration_config import (
    IntegrationConfigService,
    normalize_skyshop_base_url,
)

SHOP_KEY = "skyshop-webapi-key-abcd"
FAKTUROWNIA_TOKEN = "token-from-database-wxyz"


def _add_account(db, provider: IntegrationProvider, config: dict, secret: str):
    account = IntegrationAccount(
        provider=str(provider),
        label=f"Konto {provider}",
        config=config,
        secret_encrypted=encrypt_secret(secret),
        secret_hint=secret_hint(secret),
        is_active=True,
    )
    db.add(account)
    db.flush()
    IntegrationConfigService(db).bump_version()
    db.commit()
    return account


def test_secret_round_trip_and_hint() -> None:
    token = encrypt_secret(FAKTUROWNIA_TOKEN)
    assert token != FAKTUROWNIA_TOKEN.encode()
    assert FAKTUROWNIA_TOKEN.encode() not in token
    assert decrypt_secret(token) == FAKTUROWNIA_TOKEN
    assert secret_hint(FAKTUROWNIA_TOKEN).endswith("wxyz")
    assert FAKTUROWNIA_TOKEN not in secret_hint(FAKTUROWNIA_TOKEN)


def test_config_falls_back_to_env_when_no_account(db) -> None:
    config = IntegrationConfigService(db).get_fakturownia_config()
    assert config.source == ConfigSource.ENV
    assert config.domain == "testfirma"
    assert config.is_configured


def test_database_account_takes_precedence_over_env(db) -> None:
    _add_account(
        db, IntegrationProvider.FAKTUROWNIA,
        {"domain": "firma-z-bazy", "per_page": 42}, FAKTUROWNIA_TOKEN,
    )
    config = IntegrationConfigService(db).get_fakturownia_config()
    assert config.source == ConfigSource.DATABASE
    assert config.domain == "firma-z-bazy"
    assert config.api_token == FAKTUROWNIA_TOKEN
    assert config.per_page == 42
    assert config.base_url == "https://firma-z-bazy.fakturownia.pl"


def test_config_cache_is_invalidated_by_version_bump(db) -> None:
    account = _add_account(
        db, IntegrationProvider.FAKTUROWNIA, {"domain": "pierwsza"}, FAKTUROWNIA_TOKEN
    )
    service = IntegrationConfigService(db)
    assert service.get_fakturownia_config().domain == "pierwsza"

    account.config = {"domain": "druga"}
    db.flush()
    # Without a version bump the cached value is intentionally still served.
    assert service.get_fakturownia_config().domain == "pierwsza"
    service.bump_version()
    db.commit()
    assert service.get_fakturownia_config().domain == "druga"


def test_inactive_account_is_ignored(db) -> None:
    account = _add_account(
        db, IntegrationProvider.FAKTUROWNIA, {"domain": "firma-z-bazy"}, FAKTUROWNIA_TOKEN
    )
    account.is_active = False
    IntegrationConfigService(db).bump_version()
    db.commit()
    assert IntegrationConfigService(db).get_fakturownia_config().source == ConfigSource.ENV


def test_skyshop_config_from_account_and_secret_masking(db) -> None:
    _add_account(
        db, IntegrationProvider.SKYSHOP, {"base_url": "https://sklep.example.pl"}, SHOP_KEY
    )
    config = IntegrationConfigService(db).get_skyshop_config()
    assert config.base_url == "https://sklep.example.pl/api"
    assert config.api_key == SHOP_KEY
    assert config.rate_limit_rps == 1.0
    # Reading the configuration registers the secret for log masking.
    assert SHOP_KEY not in mask_secrets(f"wysyłam z kluczem {SHOP_KEY}")


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("sklep.example.pl", "https://sklep.example.pl/api"),
        ("https://sklep.example.pl/", "https://sklep.example.pl/api"),
        ("https://sklep.example.pl/api", "https://sklep.example.pl/api"),
        ("", ""),
    ],
)
def test_base_url_normalization(given: str, expected: str) -> None:
    assert normalize_skyshop_base_url(given) == expected


# ------------------------------- API ----------------------------------- #
def test_api_never_returns_the_secret(client, admin_headers, seeded_db) -> None:
    response = client.post(
        "/api/v1/settings/integrations",
        json={
            "provider": "FAKTUROWNIA",
            "label": "Konto główne",
            "config": {"domain": "mojafirma"},
            "secret": FAKTUROWNIA_TOKEN,
        },
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["secret_configured"] is True
    assert body["secret_hint"].endswith("wxyz")
    assert "secret" not in body
    assert FAKTUROWNIA_TOKEN not in response.text

    listed = client.get("/api/v1/settings/integrations", headers=admin_headers)
    assert FAKTUROWNIA_TOKEN not in listed.text

    # The audit trail records the change without the value.
    entries = seeded_db.execute(
        select(AuditLog).where(AuditLog.object_type == "integration_account")
    ).scalars().all()
    assert entries
    assert FAKTUROWNIA_TOKEN not in str(entries[-1].new_value)
    assert entries[-1].new_value["secret_hint"].endswith("wxyz")


def test_api_update_without_secret_keeps_stored_one(client, admin_headers, seeded_db) -> None:
    created = client.post(
        "/api/v1/settings/integrations",
        json={
            "provider": "SKYSHOP",
            "label": "Sklep główny",
            "config": {"base_url": "sklep.example.pl"},
            "secret": SHOP_KEY,
        },
        headers=admin_headers,
    ).json()
    account_id = created["id"]
    assert created["config"]["base_url"] == "https://sklep.example.pl/api"

    updated = client.patch(
        f"/api/v1/settings/integrations/{account_id}",
        json={"label": "Sklep outdoor"},
        headers=admin_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["secret_configured"] is True
    assert updated.json()["label"] == "Sklep outdoor"

    account = seeded_db.get(IntegrationAccount, account_id)
    assert decrypt_secret(account.secret_encrypted) == SHOP_KEY


def test_api_rejects_unknown_config_keys_and_missing_required(client, admin_headers) -> None:
    bad_key = client.post(
        "/api/v1/settings/integrations",
        json={
            "provider": "FAKTUROWNIA",
            "label": "Złe klucze",
            "config": {"domain": "firma", "api_token": "nie tutaj"},
        },
        headers=admin_headers,
    )
    assert bad_key.status_code == 400
    assert "api_token" in bad_key.json()["detail"]

    missing_domain = client.post(
        "/api/v1/settings/integrations",
        json={"provider": "FAKTUROWNIA", "label": "Bez domeny", "config": {}},
        headers=admin_headers,
    )
    assert missing_domain.status_code == 400


def test_api_soft_delete_and_effective_configuration(client, admin_headers) -> None:
    created = client.post(
        "/api/v1/settings/integrations",
        json={
            "provider": "FAKTUROWNIA",
            "label": "Konto do wyłączenia",
            "config": {"domain": "zbazy"},
            "secret": FAKTUROWNIA_TOKEN,
        },
        headers=admin_headers,
    ).json()

    effective = client.get(
        "/api/v1/settings/integrations/effective", headers=admin_headers
    ).json()
    fakturownia = next(e for e in effective if e["provider"] == "FAKTUROWNIA")
    assert fakturownia["source"] == "DATABASE"
    assert fakturownia["target"] == "https://zbazy.fakturownia.pl"

    deleted = client.delete(
        f"/api/v1/settings/integrations/{created['id']}", headers=admin_headers
    )
    assert deleted.status_code == 200

    effective_after = client.get(
        "/api/v1/settings/integrations/effective", headers=admin_headers
    ).json()
    assert next(
        e for e in effective_after if e["provider"] == "FAKTUROWNIA"
    )["source"] == "ENV"


def test_integration_endpoints_require_admin(client) -> None:
    assert client.get("/api/v1/settings/integrations").status_code == 401
