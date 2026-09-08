"""Resolution of effective integration configuration.

Order of precedence for every provider:

1. the active :class:`~app.models.integration.IntegrationAccount` row
   (configured in the UI, secret decrypted on read),
2. environment variables (backwards compatibility with ``.env`` installs),
3. nothing configured — the caller gets a config with ``is_configured``
   false and can render a helpful message instead of crashing.

Configuration is cached per process and invalidated through a monotonically
increasing version counter kept in ``app_settings`` — so a change made by one
uvicorn worker is picked up by all of them without a restart.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.logging_config import register_secret
from app.models.enums import ConfigSource, IntegrationProvider
from app.models.integration import IntegrationAccount
from app.models.settings import AppSetting
from app.security.crypto import SecretDecryptionError, decrypt_secret

logger = logging.getLogger(__name__)

CONFIG_VERSION_SETTING = "integration_config_version"


@dataclass(frozen=True)
class FakturowniaConfig:
    """Effective connection parameters for the read-only Fakturownia client."""

    domain: str = ""
    api_token: str = ""
    per_page: int = 100
    rate_limit_rps: float = 2.0
    max_retries: int = 5
    timeout_seconds: float = 30.0
    source: ConfigSource = ConfigSource.NONE
    account_id: int | None = None
    label: str | None = None

    @property
    def base_url(self) -> str:
        return f"https://{self.domain}.fakturownia.pl"

    @property
    def is_configured(self) -> bool:
        return bool(self.domain and self.api_token)


@dataclass(frozen=True)
class SkyShopConfig:
    """Effective connection parameters for the SkyShop WebAPI client."""

    base_url: str = ""
    api_key: str = ""
    # SkyShop WebAPI allows one request per second — never raise this blindly.
    rate_limit_rps: float = 1.0
    max_retries: int = 4
    timeout_seconds: float = 30.0
    source: ConfigSource = ConfigSource.NONE
    account_id: int | None = None
    label: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key)


class IntegrationConfigService:
    """Reads, caches and invalidates effective integration configuration."""

    _lock = Lock()
    _cache: dict[str, tuple[int, Any]] = {}

    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------ #
    # Cache plumbing
    # ------------------------------------------------------------------ #
    def _version(self) -> int:
        row = self.db.execute(
            select(AppSetting).where(AppSetting.key == CONFIG_VERSION_SETTING)
        ).scalar_one_or_none()
        try:
            return int(row.value) if row and row.value is not None else 0
        except (TypeError, ValueError):
            return 0

    def bump_version(self) -> int:
        """Invalidate the configuration cache in every worker process."""
        row = self.db.execute(
            select(AppSetting).where(AppSetting.key == CONFIG_VERSION_SETTING)
        ).scalar_one_or_none()
        if row is None:
            row = AppSetting(
                key=CONFIG_VERSION_SETTING,
                description="Licznik zmian konfiguracji integracji (unieważnia cache)",
                value=0,
            )
            self.db.add(row)
        try:
            current = int(row.value or 0)
        except (TypeError, ValueError):
            current = 0
        row.value = current + 1
        self.db.flush()
        with self._lock:
            IntegrationConfigService._cache.clear()
        return row.value

    def _cached(self, key: str, builder) -> Any:
        version = self._version()
        with self._lock:
            entry = IntegrationConfigService._cache.get(key)
            if entry is not None and entry[0] == version:
                return entry[1]
        value = builder()
        with self._lock:
            IntegrationConfigService._cache[key] = (version, value)
        return value

    @classmethod
    def clear_cache(cls) -> None:
        with cls._lock:
            cls._cache.clear()

    # ------------------------------------------------------------------ #
    # Account lookup
    # ------------------------------------------------------------------ #
    def active_account(self, provider: IntegrationProvider) -> IntegrationAccount | None:
        return self.db.execute(
            select(IntegrationAccount)
            .where(
                IntegrationAccount.provider == str(provider),
                IntegrationAccount.is_active.is_(True),
            )
            .order_by(IntegrationAccount.id)
        ).scalars().first()

    def account_secret(self, account: IntegrationAccount) -> str:
        try:
            secret = decrypt_secret(account.secret_encrypted)
        except SecretDecryptionError:
            logger.error(
                "Nie można odszyfrować sekretu konta integracji #%s (%s)",
                account.id, account.provider,
            )
            return ""
        register_secret(secret)
        return secret

    # ------------------------------------------------------------------ #
    # Fakturownia
    # ------------------------------------------------------------------ #
    def get_fakturownia_config(self) -> FakturowniaConfig:
        return self._cached("fakturownia", self._build_fakturownia_config)

    def fakturownia_config_for_account(
        self, account: IntegrationAccount
    ) -> FakturowniaConfig:
        """Configuration built from one account, active or not (used by the test button)."""
        cfg = account.config or {}
        return FakturowniaConfig(
            domain=str(cfg.get("domain") or "").strip(),
            api_token=self.account_secret(account),
            per_page=int(cfg.get("per_page") or self.settings.fakturownia_per_page),
            rate_limit_rps=float(
                cfg.get("rate_limit_rps") or self.settings.fakturownia_rate_limit_rps
            ),
            max_retries=int(cfg.get("max_retries") or self.settings.fakturownia_max_retries),
            timeout_seconds=float(
                cfg.get("timeout_seconds") or self.settings.fakturownia_timeout_seconds
            ),
            source=ConfigSource.DATABASE,
            account_id=account.id,
            label=account.label,
        )

    def _build_fakturownia_config(self) -> FakturowniaConfig:
        account = self.active_account(IntegrationProvider.FAKTUROWNIA)
        if account is not None:
            config = self.fakturownia_config_for_account(account)
            if config.is_configured:
                return config
            logger.warning(
                "Konto Fakturowni #%s jest aktywne, ale brakuje domeny lub tokenu — "
                "używam konfiguracji ze zmiennych środowiskowych",
                account.id,
            )
        return self.fakturownia_config_from_env()

    def fakturownia_config_from_env(self) -> FakturowniaConfig:
        return fakturownia_config_from_env(self.settings)

    # ------------------------------------------------------------------ #
    # SkyShop
    # ------------------------------------------------------------------ #
    def get_skyshop_config(self) -> SkyShopConfig:
        return self._cached("skyshop", self._build_skyshop_config)

    def skyshop_config_for_account(
        self, account: IntegrationAccount, max_retries: int | None = None
    ) -> SkyShopConfig:
        cfg = dict(account.config or {})
        return SkyShopConfig(
            base_url=normalize_skyshop_base_url(str(cfg.get("base_url") or "")),
            api_key=self.account_secret(account),
            rate_limit_rps=float(
                cfg.get("rate_limit_rps") or self.settings.skyshop_rate_limit_rps
            ),
            max_retries=max_retries or int(
                cfg.get("max_retries") or self.settings.skyshop_max_retries
            ),
            timeout_seconds=float(
                cfg.get("timeout_seconds") or self.settings.skyshop_timeout_seconds
            ),
            source=ConfigSource.DATABASE,
            account_id=account.id,
            label=account.label,
            extra={
                k: v for k, v in cfg.items()
                if k not in {"base_url", "rate_limit_rps", "max_retries", "timeout_seconds"}
            },
        )

    def _build_skyshop_config(self) -> SkyShopConfig:
        account = self.active_account(IntegrationProvider.SKYSHOP)
        if account is not None:
            config = self.skyshop_config_for_account(account)
            if config.is_configured:
                return config
            logger.warning(
                "Konto SkyShop #%s jest aktywne, ale brakuje adresu API lub klucza",
                account.id,
            )
        return self.skyshop_config_from_env()

    def skyshop_config_from_env(self) -> SkyShopConfig:
        return skyshop_config_from_env(self.settings)

    # ------------------------------------------------------------------ #
    # Verification bookkeeping
    # ------------------------------------------------------------------ #
    def record_verification(
        self, account: IntegrationAccount, ok: bool, error: str | None = None
    ) -> None:
        account.verified_at = datetime.now(timezone.utc)
        account.verified_status = "OK" if ok else "FAILED"
        account.verified_error = None if ok else (error or "")[:2000]


def fakturownia_config_from_env(settings: Settings | None = None) -> FakturowniaConfig:
    """Fallback configuration built purely from environment variables."""
    settings = settings or get_settings()
    token = settings.fakturownia_api_token.get_secret_value()
    if not (settings.fakturownia_domain and token):
        return FakturowniaConfig(source=ConfigSource.NONE)
    return FakturowniaConfig(
        domain=settings.fakturownia_domain,
        api_token=token,
        per_page=settings.fakturownia_per_page,
        rate_limit_rps=settings.fakturownia_rate_limit_rps,
        max_retries=settings.fakturownia_max_retries,
        timeout_seconds=settings.fakturownia_timeout_seconds,
        source=ConfigSource.ENV,
        label="Konfiguracja z .env",
    )


def skyshop_config_from_env(settings: Settings | None = None) -> SkyShopConfig:
    settings = settings or get_settings()
    key = settings.skyshop_api_key.get_secret_value()
    base_url = normalize_skyshop_base_url(settings.skyshop_base_url)
    if not (base_url and key):
        return SkyShopConfig(source=ConfigSource.NONE)
    register_secret(key)
    return SkyShopConfig(
        base_url=base_url,
        api_key=key,
        rate_limit_rps=settings.skyshop_rate_limit_rps,
        max_retries=settings.skyshop_max_retries,
        timeout_seconds=settings.skyshop_timeout_seconds,
        source=ConfigSource.ENV,
        label="Konfiguracja z .env",
    )


def normalize_skyshop_base_url(value: str) -> str:
    """Accept a bare shop domain or a full URL and return ``https://host/api``."""
    text = (value or "").strip().rstrip("/")
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        text = f"https://{text}"
    if not text.endswith("/api"):
        text = f"{text}/api"
    return text
