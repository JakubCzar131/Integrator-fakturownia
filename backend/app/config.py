"""Application configuration.

All secrets (Fakturownia API token, JWT secret, admin bootstrap password) are
read exclusively from environment variables / `.env` and are never persisted
in the repository, the database or the logs.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- application ---
    app_name: str = "Fakturownia Control ERP/WMS"
    environment: str = Field(default="development")  # development | production | test
    debug: bool = False
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    # --- database ---
    database_url: str = "postgresql+psycopg2://erp:erp@localhost:5432/erp_wms"

    # --- security ---
    secret_key: SecretStr = SecretStr("change-me-in-production")
    access_token_expire_minutes: int = 8 * 60
    jwt_algorithm: str = "HS256"

    # --- bootstrap admin (created on first start if no users exist) ---
    admin_email: str = "admin@local"
    admin_password: SecretStr = SecretStr("admin")
    admin_full_name: str = "Administrator"

    # --- Fakturownia (READ-ONLY source system) ---
    fakturownia_domain: str = ""  # e.g. "mycompany" -> https://mycompany.fakturownia.pl
    fakturownia_api_token: SecretStr = SecretStr("")
    fakturownia_per_page: int = 100
    fakturownia_rate_limit_rps: float = 2.0  # max requests per second
    fakturownia_max_retries: int = 5
    fakturownia_timeout_seconds: float = 30.0

    # --- sync scheduler ---
    sync_schedule_enabled: bool = False
    sync_interval_minutes: int = 60

    @property
    def fakturownia_base_url(self) -> str:
        return f"https://{self.fakturownia_domain}.fakturownia.pl"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def secret_values(self) -> list[str]:
        """All secret values that must be masked in logs."""
        values = [
            self.fakturownia_api_token.get_secret_value(),
            self.secret_key.get_secret_value(),
            self.admin_password.get_secret_value(),
        ]
        return [v for v in values if v and len(v) >= 4]


@lru_cache
def get_settings() -> Settings:
    return Settings()
