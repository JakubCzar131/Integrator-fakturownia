from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models.product import Product
from app.services.sync_service import SyncService
from app.services.validation_service import ValidationService
from app.tests.fixtures import FakeFakturowniaClient


def _sync_and_validate(db) -> None:
    SyncService(db, FakeFakturowniaClient()).run_full_sync()
    ValidationService(db).run_validation()
    db.commit()


def test_health(client) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_login_and_me(client, admin_headers) -> None:
    response = client.get("/api/v1/auth/me", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "admin@test.local"
    assert "admin" in body["role_names"]


def test_endpoints_require_authentication(client) -> None:
    for path in ("/api/v1/invoices", "/api/v1/products", "/api/v1/stock/balances",
                 "/api/v1/validation/issues", "/api/v1/audit-log", "/api/v1/settings"):
        assert client.get(path).status_code == 401, path


def test_invoices_list_and_detail(client, admin_headers, seeded_db) -> None:
    _sync_and_validate(seeded_db)
    response = client.get("/api/v1/invoices", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert body["items"][0]["number"]

    with_issues = client.get(
        "/api/v1/invoices?validation=with_issues", headers=admin_headers
    ).json()
    assert 0 < with_issues["total"] <= 5

    invoice_id = body["items"][0]["id"]
    detail = client.get(f"/api/v1/invoices/{invoice_id}", headers=admin_headers).json()
    assert detail["raw"]["number"] == detail["number"]
    assert isinstance(detail["positions"], list)


def test_invoice_positions_filtering(client, admin_headers, seeded_db) -> None:
    _sync_and_validate(seeded_db)
    unmapped = client.get(
        "/api/v1/invoice-positions?mapping_status=UNMAPPED", headers=admin_headers
    ).json()
    assert unmapped["total"] == 1
    assert unmapped["items"][0]["name"] == "Tajemniczy gadżet XYZ"


def test_products_and_local_classification(client, admin_headers, seeded_db) -> None:
    _sync_and_validate(seeded_db)
    products = client.get("/api/v1/products", headers=admin_headers).json()
    assert products["total"] == 3
    product_id = products["items"][0]["id"]
    response = client.patch(
        f"/api/v1/products/{product_id}",
        json={"kind": "IGNORED", "is_stock_controlled": False},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["kind"] == "IGNORED"


def test_opening_balance_and_recalculate_flow(client, admin_headers, seeded_db) -> None:
    _sync_and_validate(seeded_db)
    widget_a = seeded_db.execute(
        select(Product).where(Product.name == "Widget A")
    ).scalar_one()
    response = client.post(
        "/api/v1/stock/opening-balances",
        json={
            "product_id": widget_a.id, "warehouse_id": 1,
            "quantity": "100", "as_of_date": "2025-01-01",
            "note": "Inwentaryzacja",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text

    response = client.post("/api/v1/stock/recalculate", headers=admin_headers)
    assert response.status_code == 200

    balances = client.get(
        f"/api/v1/stock/balances?product_id={widget_a.id}", headers=admin_headers
    ).json()
    assert balances["items"][0]["quantity"] == "92.0000"


def test_local_adjustment_flow_with_audit(client, admin_headers, seeded_db) -> None:
    _sync_and_validate(seeded_db)
    widget_b = seeded_db.execute(
        select(Product).where(Product.name == "Widget B")
    ).scalar_one()
    response = client.post(
        "/api/v1/stock/local-adjustments",
        json={
            "product_id": widget_b.id, "warehouse_id": 1,
            "quantity_change": "25", "description": "Przyjęcie ręczne po inwentaryzacji",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    audit = client.get(
        "/api/v1/audit-log?object_type=stock_adjustment", headers=admin_headers
    ).json()
    assert audit["total"] >= 1
    assert "Przyjęcie ręczne" in audit["items"][0]["description"]


def test_validation_issue_status_and_comment(client, admin_headers, seeded_db) -> None:
    _sync_and_validate(seeded_db)
    issues = client.get(
        "/api/v1/validation/issues?issue_type=NEGATIVE_STOCK", headers=admin_headers
    ).json()
    assert issues["total"] >= 1
    issue_id = issues["items"][0]["id"]

    response = client.post(
        f"/api/v1/validation/issues/{issue_id}/comments",
        json={"body": "Wyjaśniam z magazynem"},
        headers=admin_headers,
    )
    assert response.status_code == 201

    response = client.patch(
        f"/api/v1/validation/issues/{issue_id}",
        json={"status": "IGNORED"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "IGNORED"
    assert response.json()["comments"][0]["body"] == "Wyjaśniam z magazynem"


def test_product_mapping_endpoint_flow(client, admin_headers, seeded_db) -> None:
    _sync_and_validate(seeded_db)
    mappings = client.get(
        "/api/v1/product-mappings?search=Tajemniczy", headers=admin_headers
    ).json()
    assert mappings["total"] == 1
    mapping_id = mappings["items"][0]["id"]
    widget_b = seeded_db.execute(
        select(Product).where(Product.name == "Widget B")
    ).scalar_one()

    response = client.patch(
        f"/api/v1/product-mappings/{mapping_id}",
        json={"product_id": widget_b.id, "status": "CONFIRMED"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "CONFIRMED"

    unmapped = client.get(
        "/api/v1/invoice-positions?mapping_status=UNMAPPED", headers=admin_headers
    ).json()
    assert unmapped["total"] == 0


def test_reports_json_csv_xlsx_pdf(client, admin_headers, seeded_db) -> None:
    _sync_and_validate(seeded_db)
    response = client.get("/api/v1/reports/sales", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["row_count"] >= 1

    csv_response = client.get("/api/v1/reports/sales?format=csv", headers=admin_headers)
    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.headers["content-type"]
    assert "Widget A".encode() in csv_response.content

    xlsx_response = client.get(
        "/api/v1/reports/negative-stock?format=xlsx", headers=admin_headers
    )
    assert xlsx_response.status_code == 200
    assert xlsx_response.content[:2] == b"PK"  # zip magic = xlsx

    pdf_response = client.get(
        "/api/v1/reports/unmapped-products?format=pdf", headers=admin_headers
    )
    assert pdf_response.status_code == 200
    assert pdf_response.content[:5] == b"%PDF-"


def test_dashboard(client, admin_headers, seeded_db) -> None:
    _sync_and_validate(seeded_db)
    body = client.get("/api/v1/dashboard", headers=admin_headers).json()
    assert body["invoice_count"] == 5
    assert body["product_count"] == 3
    assert body["client_count"] == 2
    assert body["unmapped_position_count"] == 1
    assert body["last_validation"]["status"] == "SUCCESS"


def test_settings_do_not_expose_token(client, admin_headers) -> None:
    body = client.get("/api/v1/settings", headers=admin_headers).json()
    assert body["fakturownia"]["token_configured"] is True
    assert "super-secret-test-token" not in str(body)


def test_settings_update_and_audit(client, admin_headers) -> None:
    response = client.patch(
        "/api/v1/settings",
        json={"values": {"validation_max_reasonable_quantity": 5000}},
        headers=admin_headers,
    )
    assert response.status_code == 200
    body = client.get("/api/v1/settings", headers=admin_headers).json()
    entry = next(
        s for s in body["settings"] if s["key"] == "validation_max_reasonable_quantity"
    )
    assert entry["value"] == 5000


def test_rbac_operator_cannot_manage_users(client, admin_headers) -> None:
    response = client.post(
        "/api/v1/users",
        json={"email": "operator@example.com", "password": "operator-pass-123",
              "full_name": "Operator", "roles": ["operator"]},
        headers=admin_headers,
    )
    assert response.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        data={"username": "operator@example.com", "password": "operator-pass-123"},
    )
    operator_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert client.get("/api/v1/users", headers=operator_headers).status_code == 403
    assert client.get("/api/v1/invoices", headers=operator_headers).status_code == 200


def test_rbac_auditor_is_read_only(client, admin_headers, seeded_db) -> None:
    _sync_and_validate(seeded_db)
    client.post(
        "/api/v1/users",
        json={"email": "auditor@example.com", "password": "auditor-pass-123",
              "full_name": "Audytor", "roles": ["auditor"]},
        headers=admin_headers,
    )
    login = client.post(
        "/api/v1/auth/login",
        data={"username": "auditor@example.com", "password": "auditor-pass-123"},
    )
    auditor_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert client.get("/api/v1/invoices", headers=auditor_headers).status_code == 200
    assert client.get("/api/v1/validation/issues", headers=auditor_headers).status_code == 200
    # write operations are forbidden for auditors
    widget = seeded_db.execute(select(Product)).scalars().first()
    response = client.post(
        "/api/v1/stock/opening-balances",
        json={"product_id": widget.id, "warehouse_id": 1,
              "quantity": "1", "as_of_date": "2025-01-01"},
        headers=auditor_headers,
    )
    assert response.status_code == 403
    assert client.post("/api/v1/stock/recalculate", headers=auditor_headers).status_code == 403


def test_column_preferences_roundtrip(client, admin_headers) -> None:
    response = client.put(
        "/api/v1/settings/column-preferences",
        json={"table_key": "invoices", "columns": {"visible": ["number", "buyer_name"]}},
        headers=admin_headers,
    )
    assert response.status_code == 200
    body = client.get(
        "/api/v1/settings/column-preferences/invoices", headers=admin_headers
    ).json()
    assert body["columns"]["visible"] == ["number", "buyer_name"]


def test_sync_runs_endpoint(client, admin_headers, seeded_db) -> None:
    _sync_and_validate(seeded_db)
    body = client.get("/api/v1/sync/runs", headers=admin_headers).json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "SUCCESS"
    status = client.get("/api/v1/sync/status", headers=admin_headers).json()
    assert status["last_success"]["id"] == body["items"][0]["id"]
