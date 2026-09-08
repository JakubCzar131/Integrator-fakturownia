from __future__ import annotations

from sqlalchemy.orm import Session

from app.audit.service import (
    readonly_violation_audit_callback,
    skyshop_write_audit_callback,
)
from app.database.session import SessionLocal
from app.services.fakturownia_client import FakturowniaClient
from app.services.integration_config import IntegrationConfigService
from app.services.skyshop_client import SkyShopClient
from app.services.skyshop_service import is_dry_run, is_write_enabled


def build_fakturownia_client(db: Session | None = None) -> FakturowniaClient:
    """Client factory: configuration from the database, read-only audit hook wired in.

    When no session is supplied a short-lived one is opened just to resolve the
    configuration, so background threads can call this without ceremony.
    """
    if db is not None:
        config = IntegrationConfigService(db).get_fakturownia_config()
    else:
        session = SessionLocal()
        try:
            config = IntegrationConfigService(session).get_fakturownia_config()
        finally:
            session.close()
    return FakturowniaClient(
        config=config,
        audit_callback=readonly_violation_audit_callback(SessionLocal),
    )


def build_skyshop_client(
    db: Session, user_id: int | None = None, force_write: bool = False
) -> SkyShopClient:
    """SkyShop client factory honouring the kill switch and dry-run setting.

    ``force_write`` is used by the connection test, which only ever reads.
    """
    config = IntegrationConfigService(db).get_skyshop_config()
    return SkyShopClient(
        config=config,
        write_enabled=force_write or is_write_enabled(db),
        dry_run=is_dry_run(db),
        audit_callback=skyshop_write_audit_callback(SessionLocal, user_id),
    )
