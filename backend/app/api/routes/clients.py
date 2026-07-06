from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.fakturownia import FakturowniaClient as FakturowniaClientRow
from app.models.user import User
from app.repositories.pagination import PageParams, apply_sort, paginate
from app.schemas.common import Page
from app.schemas.domain import FakturowniaClientOut
from app.security.auth import require_any_role

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=Page[FakturowniaClientOut])
def list_clients(
    params: PageParams = Depends(),
    search: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_any_role),
) -> dict:
    query = select(FakturowniaClientRow)
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                FakturowniaClientRow.name.ilike(pattern),
                FakturowniaClientRow.tax_no.ilike(pattern),
                FakturowniaClientRow.email.ilike(pattern),
            )
        )
    sortable = {
        "id": FakturowniaClientRow.id,
        "name": FakturowniaClientRow.name,
        "tax_no": FakturowniaClientRow.tax_no,
        "city": FakturowniaClientRow.city,
    }
    if not params.sort_by:
        query = query.order_by(FakturowniaClientRow.name)
    query = apply_sort(query, params, sortable)
    result = paginate(db, query, params)
    return {
        **{k: result[k] for k in ("total", "page", "per_page", "pages")},
        "items": [FakturowniaClientOut.model_validate(row[0]) for row in result["rows"]],
    }
