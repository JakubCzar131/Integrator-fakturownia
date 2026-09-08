"""Integration accounts: credentials managed in the app instead of .env.

Security rules enforced here:

* a secret is accepted only inbound; no response ever contains it,
* the audit trail records *that* a secret changed (old/new hint), never its value,
* saving bumps the configuration version, so every worker picks up the change,
* deleting is a soft deactivation — the audit trail must stay meaningful.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.database.session import get_db
from app.models.enums import AuditAction, IntegrationProvider
from app.models.integration import IntegrationAccount
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.integrations import (
    ConnectionTestResult,
    EffectiveIntegrationOut,
    IntegrationAccountCreate,
    IntegrationAccountOut,
    IntegrationAccountUpdate,
)
from app.security.auth import client_ip, require_admin
from app.security.crypto import encrypt_secret, secret_hint
from app.services.fakturownia_client import FakturowniaClient, FakturowniaError
from app.services.integration_config import (
    IntegrationConfigService,
    normalize_skyshop_base_url,
)
from app.services.skyshop_client import SkyShopClient, SkyShopError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings/integrations", tags=["integrations"])

# Non-secret keys accepted in `config`, per provider.
ALLOWED_CONFIG_KEYS = {
    str(IntegrationProvider.FAKTUROWNIA): {
        "domain", "per_page", "rate_limit_rps", "max_retries", "timeout_seconds",
    },
    str(IntegrationProvider.SKYSHOP): {
        "base_url", "rate_limit_rps", "max_retries", "timeout_seconds", "endpoints",
    },
}


def _serialize(
    account: IntegrationAccount, effective_account_ids: set[int]
) -> IntegrationAccountOut:
    out = IntegrationAccountOut.model_validate(account)
    out.secret_configured = account.secret_configured
    out.is_effective = account.id in effective_account_ids
    return out


def _effective_account_ids(service: IntegrationConfigService) -> set[int]:
    ids = {
        service.get_fakturownia_config().account_id,
        service.get_skyshop_config().account_id,
    }
    return {i for i in ids if i is not None}


def _validate_config(provider: str, config: dict) -> dict:
    allowed = ALLOWED_CONFIG_KEYS.get(provider, set())
    unknown = set(config) - allowed
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Nieznane klucze konfiguracji dla {provider}: {sorted(unknown)}",
        )
    cleaned = dict(config)
    if provider == str(IntegrationProvider.FAKTUROWNIA):
        domain = str(cleaned.get("domain") or "").strip()
        if not domain:
            raise HTTPException(
                status_code=400,
                detail="Pole „domain” jest wymagane (np. „mojafirma” dla "
                       "mojafirma.fakturownia.pl)",
            )
        # Tolerate a pasted full address.
        domain = domain.replace("https://", "").replace("http://", "").rstrip("/")
        cleaned["domain"] = domain.split(".")[0]
    if provider == str(IntegrationProvider.SKYSHOP):
        base_url = normalize_skyshop_base_url(str(cleaned.get("base_url") or ""))
        if not base_url:
            raise HTTPException(
                status_code=400,
                detail="Pole „base_url” jest wymagane (adres sklepu, np. "
                       "https://sklep.example.pl)",
            )
        cleaned["base_url"] = base_url
    return cleaned


@router.get("", response_model=list[IntegrationAccountOut])
def list_accounts(
    db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> list[IntegrationAccountOut]:
    service = IntegrationConfigService(db)
    effective = _effective_account_ids(service)
    accounts = db.execute(
        select(IntegrationAccount).order_by(
            IntegrationAccount.provider, IntegrationAccount.id
        )
    ).scalars().all()
    return [_serialize(account, effective) for account in accounts]


@router.get("/effective", response_model=list[EffectiveIntegrationOut])
def effective_configuration(
    db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> list[EffectiveIntegrationOut]:
    """What the application uses right now (database entry or .env fallback)."""
    service = IntegrationConfigService(db)
    fakturownia = service.get_fakturownia_config()
    skyshop = service.get_skyshop_config()
    return [
        EffectiveIntegrationOut(
            provider=str(IntegrationProvider.FAKTUROWNIA),
            source=str(fakturownia.source),
            is_configured=fakturownia.is_configured,
            label=fakturownia.label,
            account_id=fakturownia.account_id,
            target=fakturownia.base_url if fakturownia.is_configured else None,
            details={
                "per_page": fakturownia.per_page,
                "rate_limit_rps": fakturownia.rate_limit_rps,
                "access": "read-only (GET)",
            },
        ),
        EffectiveIntegrationOut(
            provider=str(IntegrationProvider.SKYSHOP),
            source=str(skyshop.source),
            is_configured=skyshop.is_configured,
            label=skyshop.label,
            account_id=skyshop.account_id,
            target=skyshop.base_url or None,
            details={
                "rate_limit_rps": skyshop.rate_limit_rps,
                "access": "read + write (kontrolowany przełącznikiem)",
            },
        ),
    ]


@router.post("", response_model=IntegrationAccountOut, status_code=201)
def create_account(
    payload: IntegrationAccountCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> IntegrationAccountOut:
    config = _validate_config(payload.provider, payload.config)
    duplicate = db.execute(
        select(IntegrationAccount).where(
            IntegrationAccount.provider == payload.provider,
            IntegrationAccount.label == payload.label,
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(
            status_code=409, detail="Konto o tej nazwie już istnieje dla tego dostawcy"
        )

    account = IntegrationAccount(
        provider=payload.provider,
        label=payload.label,
        config=config,
        is_active=payload.is_active,
        verified_status="NEVER",
        created_by_user_id=user.id,
        updated_by_user_id=user.id,
    )
    if payload.secret:
        account.secret_encrypted = encrypt_secret(payload.secret)
        account.secret_hint = secret_hint(payload.secret)
    db.add(account)
    db.flush()

    record_audit(
        db, AuditAction.CREATE, user=user, object_type="integration_account",
        object_id=account.id,
        description=f"Dodano konto integracji {payload.provider}: {payload.label}",
        # The secret value is deliberately absent — only its hint is stored.
        new_value={
            "provider": payload.provider,
            "label": payload.label,
            "config": config,
            "secret_hint": account.secret_hint,
            "is_active": payload.is_active,
        },
        ip_address=client_ip(request),
    )
    IntegrationConfigService(db).bump_version()
    db.commit()
    db.refresh(account)
    service = IntegrationConfigService(db)
    return _serialize(account, _effective_account_ids(service))


@router.patch("/{account_id}", response_model=IntegrationAccountOut)
def update_account(
    account_id: int,
    payload: IntegrationAccountUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> IntegrationAccountOut:
    account = db.get(IntegrationAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Konto integracji nie istnieje")

    old = {
        "label": account.label,
        "config": dict(account.config or {}),
        "secret_hint": account.secret_hint,
        "is_active": account.is_active,
    }
    if payload.label is not None:
        account.label = payload.label
    if payload.config is not None:
        account.config = _validate_config(account.provider, payload.config)
    if payload.is_active is not None:
        account.is_active = payload.is_active
    if payload.secret:
        account.secret_encrypted = encrypt_secret(payload.secret)
        account.secret_hint = secret_hint(payload.secret)
        account.verified_status = "NEVER"
        account.verified_at = None
        account.verified_error = None
    account.updated_by_user_id = user.id

    record_audit(
        db, AuditAction.UPDATE, user=user, object_type="integration_account",
        object_id=account.id,
        description=f"Zmieniono konto integracji {account.provider}: {account.label}"
                    + (" (zmieniono sekret)" if payload.secret else ""),
        old_value=old,
        new_value={
            "label": account.label,
            "config": dict(account.config or {}),
            "secret_hint": account.secret_hint,
            "is_active": account.is_active,
        },
        ip_address=client_ip(request),
    )
    IntegrationConfigService(db).bump_version()
    db.commit()
    db.refresh(account)
    service = IntegrationConfigService(db)
    return _serialize(account, _effective_account_ids(service))


@router.delete("/{account_id}", response_model=MessageResponse)
def deactivate_account(
    account_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> MessageResponse:
    """Soft delete: the account is deactivated so the audit trail stays intact."""
    account = db.get(IntegrationAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Konto integracji nie istnieje")
    account.is_active = False
    account.updated_by_user_id = user.id
    record_audit(
        db, AuditAction.DELETE, user=user, object_type="integration_account",
        object_id=account.id,
        description=f"Dezaktywowano konto integracji {account.provider}: {account.label}",
        ip_address=client_ip(request),
    )
    IntegrationConfigService(db).bump_version()
    db.commit()
    return MessageResponse(message="Konto integracji zostało dezaktywowane")


@router.post("/{account_id}/test-connection", response_model=ConnectionTestResult)
def test_connection(
    account_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> ConnectionTestResult:
    """Live read-only check of the stored credentials."""
    account = db.get(IntegrationAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Konto integracji nie istnieje")

    service = IntegrationConfigService(db)
    ok, message, detail = False, "", None
    try:
        if account.provider == str(IntegrationProvider.FAKTUROWNIA):
            ok, message, detail = _test_fakturownia(service, account)
        else:
            ok, message, detail = _test_skyshop(service, account)
    except (FakturowniaError, SkyShopError) as exc:
        message = str(exc)
    except Exception as exc:  # noqa: BLE001 - surface any connection problem
        logger.exception("Test połączenia %s nie powiódł się", account.provider)
        message = str(exc)

    service.record_verification(account, ok, None if ok else message)
    record_audit(
        db, AuditAction.INTEGRATION_TESTED, user=user, object_type="integration_account",
        object_id=account.id,
        description=f"Test połączenia {account.provider} ({account.label}): "
                    f"{'OK' if ok else 'BŁĄD'}",
        new_value={"ok": ok, "message": message},
        ip_address=client_ip(request),
    )
    db.commit()
    return ConnectionTestResult(ok=ok, message=message, detail=detail)


def _test_fakturownia(
    service: IntegrationConfigService, account: IntegrationAccount
) -> tuple[bool, str, dict | None]:
    config = service.fakturownia_config_for_account(account)
    if not config.is_configured:
        return False, "Brak domeny lub tokenu API", None
    with FakturowniaClient(config=config) as client:
        departments = client.get_departments()
    return (
        True,
        f"Połączenie OK — odczytano {len(departments)} działów (tylko GET)",
        {"departments": len(departments), "base_url": config.base_url},
    )


def _test_skyshop(
    service: IntegrationConfigService, account: IntegrationAccount
) -> tuple[bool, str, dict | None]:
    # A connection test must fail fast, hence the single attempt.
    config = service.skyshop_config_for_account(account, max_retries=1)
    if not config.is_configured:
        return False, "Brak adresu sklepu lub klucza WebAPI", None
    # Writes stay disabled here: a test must never mutate the shop.
    with SkyShopClient(config=config, write_enabled=False, dry_run=True) as client:
        client.ping()
    return (
        True,
        "Połączenie OK — sklep odpowiedział na zapytanie odczytu",
        {"base_url": config.base_url},
    )
