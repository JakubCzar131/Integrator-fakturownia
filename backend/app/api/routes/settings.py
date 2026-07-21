from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.config import get_settings
from app.database.session import get_db
from app.models.enums import AuditAction
from app.models.settings import AppSetting, TableColumnPreference
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.domain import AppSettingOut, ColumnPreferenceIn, SettingsUpdate
from app.security.auth import client_ip, get_current_user, require_admin
from app.services.stock_service import (
    DEFAULT_EXCLUDED_STATUSES,
    DEFAULT_SALE_KINDS,
    SETTING_EXCLUDED_STATUSES,
    SETTING_SALE_KINDS,
    SETTING_USE_WAREHOUSE_ACTIONS,
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
}


@router.get("", response_model=dict)
def get_app_settings(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    env = get_settings()
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
    return {
        "fakturownia": {
            "domain": env.fakturownia_domain or None,
            "base_url": env.fakturownia_base_url if env.fakturownia_domain else None,
            "token_configured": bool(env.fakturownia_api_token.get_secret_value()),
            # The token itself is NEVER returned by the API.
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
