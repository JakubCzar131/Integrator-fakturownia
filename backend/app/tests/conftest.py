from __future__ import annotations

import os

# Test environment must be configured BEFORE importing app modules.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("FAKTUROWNIA_DOMAIN", "testfirma")
os.environ.setdefault("FAKTUROWNIA_API_TOKEN", "super-secret-test-token")
os.environ.setdefault("FAKTUROWNIA_RATE_LIMIT_RPS", "0")
os.environ.setdefault("ADMIN_EMAIL", "admin@test.local")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings

get_settings.cache_clear()

from app.bootstrap import seed_roles_and_admin
from app.database.base import Base
from app.database.session import get_db
from app.main import create_app
import app.models  # noqa: F401


@pytest.fixture(autouse=True)
def isolated_integration_config():
    """Each test gets its own database, so the cross-request config cache must reset."""
    from app.logging_config import clear_registered_secrets
    from app.services.integration_config import IntegrationConfigService

    IntegrationConfigService.clear_cache()
    clear_registered_secrets()
    yield
    IntegrationConfigService.clear_cache()
    clear_registered_secrets()


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(engine) -> Session:
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSession()
    yield session
    session.close()


@pytest.fixture()
def seeded_db(db: Session) -> Session:
    seed_roles_and_admin(db)
    return db


@pytest.fixture()
def client(seeded_db: Session):
    app = create_app()

    def override_get_db():
        yield seeded_db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def admin_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "admin@test.local", "password": "test-admin-password"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
