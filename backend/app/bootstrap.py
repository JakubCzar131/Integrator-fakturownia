"""First-start seeding: roles + bootstrap admin account."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import RoleName
from app.models.user import Role, User
from app.security.passwords import hash_password

logger = logging.getLogger(__name__)

ROLE_DESCRIPTIONS = {
    RoleName.ADMIN: "Pełny dostęp: użytkownicy, ustawienia, wszystkie operacje lokalne",
    RoleName.OPERATOR: "Operacje lokalne: synchronizacja, mapowania, korekty, walidacje",
    RoleName.AUDITOR: "Tylko odczyt: przegląd danych, raportów i audytu",
}


def seed_roles_and_admin(db: Session) -> None:
    settings = get_settings()

    roles: dict[str, Role] = {}
    for role_name in RoleName:
        role = db.execute(
            select(Role).where(Role.name == str(role_name))
        ).scalar_one_or_none()
        if role is None:
            role = Role(name=str(role_name), description=ROLE_DESCRIPTIONS[role_name])
            db.add(role)
        roles[str(role_name)] = role
    db.flush()

    has_users = db.execute(select(User.id).limit(1)).first() is not None
    if not has_users:
        admin = User(
            email=settings.admin_email.lower().strip(),
            full_name=settings.admin_full_name,
            hashed_password=hash_password(settings.admin_password.get_secret_value()),
            roles=[roles[str(RoleName.ADMIN)]],
        )
        db.add(admin)
        logger.info("Created bootstrap admin account: %s", settings.admin_email)
    db.commit()
