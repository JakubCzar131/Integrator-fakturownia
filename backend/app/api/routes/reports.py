from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.database.session import get_db
from app.models.enums import AuditAction
from app.models.settings import ReportExport
from app.models.user import User
from app.security.auth import client_ip, require_any_role
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["reports"])

MEDIA_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
REPORT_TITLES = {
    "sales": "Sprzedaż produktów wg okresu",
    "unmapped-products": "Produkty sprzedane bez mapowania",
    "negative-stock": "Produkty ze stanem ujemnym",
    "stock-discrepancies": "Różnice magazynowe",
    "problem-invoices": "Faktury z problemami",
    "top-error-products": "Produkty najczęściej powodujące błędy",
    "stock-history": "Historia stanów magazynowych",
}


def _run_report(
    db: Session,
    report_key: str,
    date_from: date | None,
    date_to: date | None,
    product_id: int | None,
    warehouse_id: int | None,
):
    if report_key == "sales":
        return report_service.sales_report(db, date_from, date_to)
    if report_key == "stock-history":
        return report_service.stock_history_report(db, product_id, warehouse_id)
    func = report_service.REPORTS.get(report_key)
    if func is None:
        raise HTTPException(status_code=404, detail=f"Nieznany raport: {report_key}")
    return func(db)


@router.get("/{report_key}")
def get_report(
    report_key: str,
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    product_id: int | None = None,
    warehouse_id: int | None = None,
    format: str = "json",
    db: Session = Depends(get_db),
    user: User = Depends(require_any_role),
):
    if report_key not in report_service.REPORTS:
        raise HTTPException(status_code=404, detail=f"Nieznany raport: {report_key}")
    headers, rows = _run_report(db, report_key, date_from, date_to, product_id, warehouse_id)

    if format == "json":
        return {
            "report": report_key,
            "title": REPORT_TITLES.get(report_key, report_key),
            "headers": headers,
            "rows": [[report_service._stringify(v) for v in row] for row in rows],
            "row_count": len(rows),
        }

    if format not in MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="Dozwolone formaty: json, csv, xlsx, pdf")

    title = REPORT_TITLES.get(report_key, report_key)
    if format == "csv":
        content = report_service.export_csv(headers, rows)
    elif format == "xlsx":
        content = report_service.export_xlsx(headers, rows, title)
    else:
        content = report_service.export_pdf(headers, rows, title)

    file_name = f"{report_key}_{date.today().isoformat()}.{format}"
    db.add(
        ReportExport(
            user_id=user.id,
            report_key=report_key,
            format=format.upper(),
            row_count=len(rows),
            params={
                "date_from": date_from.isoformat() if date_from else None,
                "date_to": date_to.isoformat() if date_to else None,
                "product_id": product_id,
                "warehouse_id": warehouse_id,
            },
            file_name=file_name,
        )
    )
    record_audit(
        db, AuditAction.EXPORT, user=user, object_type="report", object_id=report_key,
        description=f"Eksport raportu „{title}” ({format.upper()}, {len(rows)} wierszy)",
        ip_address=client_ip(request),
    )
    db.commit()
    return Response(
        content=content,
        media_type=MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )
