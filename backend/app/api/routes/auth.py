from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.database.session import get_db
from app.models.enums import AuditAction
from app.models.user import User
from app.schemas.auth import Token, UserOut
from app.security.auth import client_ip, create_access_token, get_current_user
from app.security.passwords import verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    user = db.execute(
        select(User).where(User.email == form_data.username.lower().strip())
    ).scalar_one_or_none()
    ip = client_ip(request)
    if user is None or not verify_password(form_data.password, user.hashed_password):
        record_audit(
            db, AuditAction.LOGIN_FAILED,
            description=f"Nieudane logowanie: {form_data.username}", ip_address=ip,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nieprawidłowy e-mail lub hasło",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Konto jest nieaktywne")
    record_audit(db, AuditAction.LOGIN, user=user, description="Logowanie", ip_address=ip)
    db.commit()
    return Token(access_token=create_access_token(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
