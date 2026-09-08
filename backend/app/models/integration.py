"""Integration accounts: credentials for external systems managed in the app.

Before this table existed, the Fakturownia domain and API token could only be
set through environment variables.  Now every provider (Fakturownia, SkyShop)
is configured in *Ustawienia → Integracje*: non-secret settings land in
``config`` (JSON), the token is encrypted with Fernet in ``secret_encrypted``
(see :mod:`app.security.crypto`) and only a four-character hint is ever shown.

Environment variables still work as a fallback, so existing deployments keep
running without any manual migration (see
:class:`app.services.integration_config.IntegrationConfigService`).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, JSONVariant


class IntegrationAccount(Base):
    __tablename__ = "integration_accounts"
    __table_args__ = (
        sa.UniqueConstraint("provider", "label", name="uq_integration_accounts_provider_label"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(sa.String(30), index=True)
    label: Mapped[str] = mapped_column(sa.String(255))
    # Non-secret connection settings, e.g. {"domain": "firma", "per_page": 100}
    config: Mapped[dict[str, Any]] = mapped_column(JSONVariant(), default=dict)
    secret_encrypted: Mapped[bytes | None] = mapped_column(sa.LargeBinary)
    secret_hint: Mapped[str | None] = mapped_column(sa.String(12))
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    verified_status: Mapped[str] = mapped_column(sa.String(20), default="NEVER")
    verified_error: Mapped[str | None] = mapped_column(sa.Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    @property
    def secret_configured(self) -> bool:
        return bool(self.secret_encrypted)
