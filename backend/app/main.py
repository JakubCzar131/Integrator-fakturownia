"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import (
    audit,
    auth,
    clients,
    dashboard,
    health,
    integrations,
    invoice_positions,
    invoices,
    product_mappings,
    products,
    reconciliation,
    reports,
    settings as settings_routes,
    skyshop,
    stock,
    sync,
    users,
    validation,
    warehouse_documents,
)
from app.config import get_settings
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    if settings.environment != "test":
        try:
            from app.bootstrap import seed_roles_and_admin
            from app.database.session import SessionLocal

            db = SessionLocal()
            try:
                seed_roles_and_admin(db)
            finally:
                db.close()
        except Exception:
            logger.exception(
                "Bootstrap seeding failed (is the database migrated? run `alembic upgrade head`)"
            )
        from app.services.scheduler import start_scheduler, stop_scheduler

        start_scheduler()
        yield
        stop_scheduler()
    else:
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Integrator Fakturownia ↔ SkyShop: lokalny panel kontrolny ERP/WMS dla "
            "sprzedaży prowadzonej w Fakturowni plus synchronizacja stanów "
            "magazynowych i produktów ze sklepem SkyShop.\n\n"
            "Integracja z Fakturownią jest **wyłącznie do odczytu (GET)** — klient API "
            "technicznie blokuje wszystkie metody zapisu. Jedynym kierunkiem zapisu "
            "jest SkyShop: osobny klient, globalny kill-switch, tryb dry-run oraz "
            "audyt każdej mutacji."
        ),
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    prefix = settings.api_prefix
    app.include_router(health.router, prefix=prefix)
    app.include_router(auth.router, prefix=prefix)
    app.include_router(users.router, prefix=prefix)
    app.include_router(dashboard.router, prefix=prefix)
    app.include_router(sync.router, prefix=prefix)
    app.include_router(invoices.router, prefix=prefix)
    app.include_router(invoice_positions.router, prefix=prefix)
    app.include_router(products.router, prefix=prefix)
    app.include_router(product_mappings.router, prefix=prefix)
    app.include_router(clients.router, prefix=prefix)
    app.include_router(stock.router, prefix=prefix)
    app.include_router(warehouse_documents.router, prefix=prefix)
    app.include_router(reconciliation.router, prefix=prefix)
    app.include_router(skyshop.router, prefix=prefix)
    app.include_router(validation.router, prefix=prefix)
    app.include_router(reports.router, prefix=prefix)
    app.include_router(audit.router, prefix=prefix)
    app.include_router(settings_routes.router, prefix=prefix)
    app.include_router(integrations.router, prefix=prefix)
    return app


app = create_app()
