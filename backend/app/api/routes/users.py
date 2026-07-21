from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.database.session import get_db
from app.models.enums import AuditAction
from app.models.user import Role, User
from app.schemas.auth import RoleOut, UserCreate, UserOut, UserUpdate
from app.security.auth import client_ip, require_admin
from app.security.passwords import hash_password

router = APIRouter(prefix="/users", tags=["users"])


def _resolve_roles(db: Session, names: list[str]) -> list[Role]:
    roles = db.execute(select(Role).where(Role.name.in_(names))).scalars().all()
    missing = set(names) - {r.name for r in roles}
    if missing:
        raise HTTPException(status_code=400, detail=f"Nieznane role: {sorted(missing)}")
    return list(roles)


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> list[User]:
    return list(db.execute(select(User).order_by(User.id)).scalars())


@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> list[Role]:
    return list(db.execute(select(Role).order_by(Role.id)).scalars())


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> User:
    email = payload.email.lower().strip()
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Użytkownik o tym adresie już istnieje")
    user = User(
        email=email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        roles=_resolve_roles(db, payload.roles),
    )
    db.add(user)
    db.flush()
    record_audit(
        db, AuditAction.CREATE, user=admin, object_type="user", object_id=user.id,
        description=f"Utworzono użytkownika {email}",
        new_value={"email": email, "roles": payload.roles},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Użytkownik nie istnieje")
    old = {"full_name": user.full_name, "is_active": user.is_active, "roles": user.role_names}
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.password:
        user.hashed_password = hash_password(payload.password)
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.roles is not None:
        user.roles = _resolve_roles(db, payload.roles)
    record_audit(
        db, AuditAction.UPDATE, user=admin, object_type="user", object_id=user.id,
        description=f"Zmieniono użytkownika {user.email}",
        old_value=old,
        new_value={
            "full_name": user.full_name, "is_active": user.is_active,
            "roles": user.role_names, "password_changed": bool(payload.password),
        },
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(user)
    return user
