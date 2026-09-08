"""Server-side pagination / sorting shared by all list endpoints."""
from __future__ import annotations

import math
from typing import Any

from fastapi import HTTPException, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


class PageParams:
    def __init__(
        self,
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=1, le=500),
        sort_by: str | None = Query(None),
        sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    ) -> None:
        self.page = page
        self.per_page = per_page
        self.sort_by = sort_by
        self.sort_dir = sort_dir


def apply_sort(query: Select, params: PageParams, sortable: dict[str, Any]) -> Select:
    if not params.sort_by:
        return query
    column = sortable.get(params.sort_by)
    if column is None:
        raise HTTPException(status_code=400, detail=f"Nieznana kolumna sortowania: {params.sort_by}")
    return query.order_by(column.desc() if params.sort_dir == "desc" else column.asc())


def paginate(db: Session, query: Select, params: PageParams) -> dict[str, Any]:
    total = db.execute(
        select(func.count()).select_from(query.order_by(None).subquery())
    ).scalar_one()
    items = db.execute(
        query.limit(params.per_page).offset((params.page - 1) * params.per_page)
    ).all()
    return {
        "total": total,
        "page": params.page,
        "per_page": params.per_page,
        "pages": max(1, math.ceil(total / params.per_page)),
        "rows": items,
    }
