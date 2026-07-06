"""Declarative base with a deterministic naming convention (Alembic-friendly)."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


def JSONVariant() -> sa.types.TypeEngine:
    """JSON column that uses JSONB on PostgreSQL and plain JSON elsewhere (tests)."""
    return sa.JSON().with_variant(JSONB(astext_type=sa.Text()), "postgresql")
