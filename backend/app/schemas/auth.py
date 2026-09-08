from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RoleOut(ORMModel):
    id: int
    name: str
    description: str | None = None


class UserOut(ORMModel):
    id: int
    email: str
    full_name: str
    is_active: bool
    created_at: datetime
    role_names: list[str] = []


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = ""
    password: str = Field(min_length=8)
    roles: list[str] = ["operator"]


class UserUpdate(BaseModel):
    full_name: str | None = None
    password: str | None = Field(default=None, min_length=8)
    is_active: bool | None = None
    roles: list[str] | None = None
