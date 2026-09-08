from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.database.session import get_db
from app.models.enums import AuditAction, StockSource
from app.models.settings import AppSetting, TableColumnPreference
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.domain import AppSettingOut, ColumnPreferenceIn, SettingsUpdate
from app.security.auth import client_ip, get_current_user, require_admin
from app.services.integration_config import IntegrationConfigService
from app.services.reconciliation_service import SETTING_INCLUDE_OUTBOUND_DOCUMENTS
from app.services.skyshop_service import (
    SETTING_AUTO_STOCK_PUSH,
    SETTING_DRY_RUN,
    SETTING_MATCH_BY_NAME,
    SETTING_STOCK_SOURCE,
    SETTING_STOCK_WAREHOUSE_ID,
    SETTING_SYNC_ENABLED,
)
from app.services.stock_service import (
    DEFAULT_EXCLUDED_STATUSES,
    DEFAULT_SALE_KINDS,
    SETTING_EXCLUDED_STATUSES,
    SETTING_SALE_KINDS,
    SETTING_USE_WAREHOUSE_ACTIONS,
)
from app.services.sync_service import (
    SETTING_REBUILD_STOCK_AFTER_SYNC,
    SETTING_RECONCILE_AFTER_SYNC,
)
from app.services.validation_service import (
    SETTING_DISCREPANCY_TOLERANCE,
    SETTING_QUANTITY_MAX,
)

router = APIRouter(prefix="/settings", tags=["settings"])

# Editable application settings with defaults + descriptions.
KNOWN_SETTINGS: dict[str, tuple[object, str]] = {
    SETTING_SALE_KINDS: (
        DEFAULT_SALE_KINDS,
        "Typy dokumentów Fakturowni traktowane jako sprzedaż zdejmująca stan magazynu",
    ),
    SETTING_EXCLUDED_STATUSES: (
        DEFAULT_EXCLUDED_STATUSES,
        "Statusy dokumentów wykluczone z rozliczenia magazynowego i walidacji",
    ),
    SETTING_USE_WAREHOUSE_ACTIONS: (
        False,
        "Czy importowane akcje magazynowe z Fakturowni mają zasilać lokalny ledger",
    ),
    SETTING_QUANTITY_MAX: (
        100000,
        "Maksymalna ilość na pozycji uznawana za wiarygodną (powyżej: ostrzeżenie)",
    ),
    SETTING_DISCREPANCY_TOLERANCE: (
        "0.001",
        "Tolerancja różnicy między stanem lokalnym a stanem z Fakturowni",
    ),
    "sync_schedule_minutes": (
        None,
        "Interwał automatycznej synchronizacji przyrostowej w minutach (puste = wyłączona)",
    ),
    SETTING_REBUILD_STOCK_AFTER_SYNC: (
        True,
        "Czy po każdej synchronizacji przebudowywać lokalny ledger magazynowy",
    ),
    SETTING_RECONCILE_AFTER_SYNC: (
        True,
        "Czy po każdej synchronizacji odświeżać tabelę rozliczeniową (PZ/PW vs faktury)",
    ),
    SETTING_INCLUDE_OUTBOUND_DOCUMENTS: (
        False,
        "Czy w rozliczeniu odejmować dokumenty WZ/RW/MM (włącz tylko gdy magazyn "
        "rozchodowywany jest dokumentami, a nie fakturami — inaczej podwójne liczenie)",
    ),
    SETTING_SYNC_ENABLED: (
        False,
        "GŁÓWNY WYŁĄCZNIK zapisu do SkyShop — dopóki false, żadna mutacja nie wychodzi",
    ),
    SETTING_DRY_RUN: (
        True,
        "Tryb próbny SkyShop: payloady są budowane i audytowane, ale nie wysyłane",
    ),
    SETTING_STOCK_SOURCE: (
        str(StockSource.LOCAL_LEDGER),
        "Źródło stanu wysyłanego do SkyShop: LOCAL_LEDGER | FAKTUROWNIA | RECONCILED",
    ),
    SETTING_STOCK_WAREHOUSE_ID: (
        None,
        "Magazyn (lokalne id), z którego liczony jest stan dla sklepu (puste = suma "
        "wszystkich magazynów)",
    ),
    SETTING_AUTO_STOCK_PUSH: (
        False,
        "Czy po każdej synchronizacji automatycznie kolejkować wysyłkę zmienionych "
        "stanów do SkyShop",
    ),
    SETTING_MATCH_BY_NAME: (
        False,
        "Czy dopasowywać produkty do SkyShop także po nazwie (po SKU i EAN); "
        "ryzykowne przy powtarzalnych nazwach",
    ),
}


@router.get("", response_model=dict)
def get_app_settings(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    stored = {
        s.key: AppSettingOut.model_validate(s).model_dump()
        for s in db.execute(select(AppSetting)).scalars()
    }
    values = []
    for key, (default, description) in KNOWN_SETTINGS.items():
        entry = stored.get(key)
        values.append({
            "key": key,
            "value": entry["value"] if entry else default,
            "description": description,
            "is_default": entry is None,
        })
    # extra stored keys (e.g. last_successful_sync_at)
    for key, entry in stored.items():
        if key not in KNOWN_SETTINGS:
            values.append({**entry, "is_default": False})
    # Effective integration configuration: database entry first, .env fallback.
    # Tokens themselves are NEVER returned by the API.
    config_service = IntegrationConfigService(db)
    fakturownia = config_service.get_fakturownia_config()
    skyshop = config_service.get_skyshop_config()
    return {
        "fakturownia": {
            "domain": fakturownia.domain or None,
            "base_url": fakturownia.base_url if fakturownia.is_configured else None,
            "token_configured": bool(fakturownia.api_token),
            "source": str(fakturownia.source),
            "label": fakturownia.label,
        },
        "skyshop": {
            "base_url": skyshop.base_url or None,
            "key_configured": bool(skyshop.api_key),
            "source": str(skyshop.source),
            "label": skyshop.label,
        },
        "settings": values,
    }


@router.patch("", response_model=MessageResponse)
def update_app_settings(
    payload: SettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> MessageResponse:
    """Update local application settings (never touches Fakturownia)."""
    unknown = set(payload.values) - set(KNOWN_SETTINGS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Nieznane ustawienia: {sorted(unknown)}")
    for key, value in payload.values.items():
        row = db.execute(select(AppSetting).where(AppSetting.key == key)).scalar_one_or_none()
        old_value = row.value if row else None
        if row is None:
            row = AppSetting(key=key, description=KNOWN_SETTINGS[key][1])
            db.add(row)
        row.value = value
        row.updated_by_user_id = user.id
        record_audit(
            db, AuditAction.UPDATE, user=user, object_type="app_setting", object_id=key,
            description=f"Zmieniono ustawienie {key}",
            old_value={"value": old_value},
            new_value={"value": value},
            ip_address=client_ip(request),
        )
    db.commit()
    return MessageResponse(message="Ustawienia zapisane")


# ------------------ per-user table column preferences ------------------- #
@router.get("/column-preferences/{table_key}")
def get_column_preferences(
    table_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    row = db.execute(
        select(TableColumnPreference).where(
            TableColumnPreference.user_id == user.id,
            TableColumnPreference.table_key == table_key,
        )
    ).scalar_one_or_none()
    return {"table_key": table_key, "columns": row.columns if row else None}


@router.put("/column-preferences", response_model=MessageResponse)
def save_column_preferences(
    payload: ColumnPreferenceIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MessageResponse:
    row = db.execute(
        select(TableColumnPreference).where(
            TableColumnPreference.user_id == user.id,
            TableColumnPreference.table_key == payload.table_key,
        )
    ).scalar_one_or_none()
    if row is None:
        row = TableColumnPreference(user_id=user.id, table_key=payload.table_key, columns={})
        db.add(row)
    row.columns = payload.columns
    db.commit()
    return MessageResponse(message="Preferencje kolumn zapisane")
