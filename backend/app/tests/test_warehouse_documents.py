"""Normalization of PZ/PW positions: both payload shapes, mapping, idempotency."""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.fakturownia import WarehouseDocument, WarehouseDocumentPosition
from app.models.product import Product, ProductMapping
from app.services.mapping_service import (
    apply_document_position_mappings,
    confirm_mapping,
)
from app.services.sync_service import SyncService
from app.services.warehouse_document_service import (
    normalize_document_kind,
    rebuild_document_positions,
)
from app.tests.fixtures import FAKE_WAREHOUSE_DOCUMENTS, FakeFakturowniaClient


def _sync(db) -> None:
    SyncService(db, FakeFakturowniaClient()).run_full_sync()


def _positions(db, document_fakturownia_id: int) -> list[WarehouseDocumentPosition]:
    document = db.execute(
        select(WarehouseDocument).where(
            WarehouseDocument.fakturownia_id == document_fakturownia_id
        )
    ).scalar_one()
    return sorted(document.positions, key=lambda position: position.id)


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("PZ", "PZ"),
        ("pw", "PW"),
        ("  Wz  ", "WZ"),
        ("mm_in", "MM"),
        ("mm_out", "MM"),
        ("pz_correction", "PZ"),
        ("faktura", "OTHER"),
        (None, "OTHER"),
        ("", "OTHER"),
    ],
)
def test_document_kind_normalization(given: str | None, expected: str) -> None:
    assert normalize_document_kind(given) == expected


def test_positions_are_built_from_embedded_payload(db) -> None:
    _sync(db)
    positions = _positions(db, 7002)
    assert [position.document_kind for position in positions] == ["PW", "PW"]
    assert [position.quantity for position in positions] == [
        Decimal("30.0000"),
        Decimal("5.0000"),
    ]
    assert positions[0].purchase_price_net == Decimal("8.00")
    # Denormalized from the document header for aggregation without a join.
    assert all(str(position.issue_date) == "2025-01-05" for position in positions)
    assert all(position.warehouse_fakturownia_id == 900 for position in positions)


def test_positions_fall_back_to_warehouse_actions(db) -> None:
    """PZ 1/2025 carries no positions in its payload — the action supplies them."""
    _sync(db)
    positions = _positions(db, 7001)
    assert len(positions) == 1
    position = positions[0]
    assert position.document_kind == "PZ"
    assert position.source_action_fakturownia_id == 8001
    assert position.product_fakturownia_id == 101
    assert position.quantity == Decimal("20.0000")


def test_positions_go_through_the_shared_mapping_pipeline(db) -> None:
    _sync(db)
    widget_a = db.execute(select(Product).where(Product.name == "Widget A")).scalar_one()
    widget_b = db.execute(select(Product).where(Product.name == "Widget B")).scalar_one()

    with_product_id, without_product_id = _positions(db, 7002)
    # product_id on the position resolves directly and needs no approval.
    assert with_product_id.mapped_product_id == widget_b.id
    assert with_product_id.mapping_status == "CONFIRMED"
    assert with_product_id.mapping_match_type == "PRODUCT_ID"
    # No product_id: recognized by code, so it awaits approval like an invoice line.
    assert without_product_id.mapped_product_id == widget_a.id
    assert without_product_id.mapping_status == "PROPOSED"
    assert without_product_id.mapping_match_type == "CODE"


def test_unrecognized_position_creates_a_mapping_panel_stub(db) -> None:
    documents = [dict(document) for document in FAKE_WAREHOUSE_DOCUMENTS]
    documents[1] = {
        **documents[1],
        "positions": [
            {"id": 8103, "product_id": None, "name": "Nieznany towar QWE",
             "code": None, "quantity": "7", "quantity_unit": "szt"},
        ],
    }
    SyncService(db, FakeFakturowniaClient(warehouse_documents=documents)).run_full_sync()

    position = _positions(db, 7002)[0]
    assert position.mapped_product_id is None
    assert position.mapping_status is None

    stub = db.execute(
        select(ProductMapping).where(ProductMapping.source_name == "Nieznany towar QWE")
    ).scalar_one()
    assert stub.status == "PROPOSED"
    assert stub.product_id is None

    # Confirming in the mapping panel must reach document positions too.
    widget_a = db.execute(select(Product).where(Product.name == "Widget A")).scalar_one()
    confirm_mapping(db, stub, widget_a.id, user_id=None)
    assert _positions(db, 7002)[0].mapped_product_id == widget_a.id


def test_rebuild_is_idempotent_and_skips_unchanged_documents(db) -> None:
    _sync(db)
    before = db.execute(select(func.count(WarehouseDocumentPosition.id))).scalar_one()

    stats = rebuild_document_positions(db)
    assert stats["unchanged"] == stats["documents"]
    assert stats["rebuilt"] == 0
    assert db.execute(select(func.count(WarehouseDocumentPosition.id))).scalar_one() == before


def test_changed_payload_replaces_positions_without_duplicating(db) -> None:
    _sync(db)
    document = db.execute(
        select(WarehouseDocument).where(WarehouseDocument.fakturownia_id == 7002)
    ).scalar_one()
    document.raw = {
        **(document.raw or {}),
        "positions": [
            {"id": 8101, "product_id": 102, "name": "Widget B", "code": "WID-B",
             "quantity": "44", "quantity_unit": "szt"},
        ],
    }
    db.flush()

    stats = rebuild_document_positions(db)
    assert stats["rebuilt"] == 1
    apply_document_position_mappings(db)

    positions = _positions(db, 7002)
    assert len(positions) == 1
    assert positions[0].quantity == Decimal("44.0000")


def test_position_kind_from_payload_wins_over_the_header(db) -> None:
    """MM documents mix directions; a position kind is more precise than the header."""
    documents = [dict(document) for document in FAKE_WAREHOUSE_DOCUMENTS]
    documents[1] = {
        **documents[1],
        "kind": "MM",
        "positions": [
            {"id": 8104, "product_id": 101, "kind": "PZ", "quantity": "3"},
            {"id": 8105, "product_id": 101, "quantity": "3"},
        ],
    }
    SyncService(db, FakeFakturowniaClient(warehouse_documents=documents)).run_full_sync()

    assert [position.document_kind for position in _positions(db, 7002)] == ["PZ", "MM"]


# ------------------------------- API ----------------------------------- #
def test_api_lists_documents_with_position_aggregates(client, admin_headers, seeded_db) -> None:
    _sync(seeded_db)
    response = client.get(
        "/api/v1/warehouse-documents?only_inbound=true", headers=admin_headers
    )
    assert response.status_code == 200, response.text
    documents = {item["number"]: item for item in response.json()["items"]}
    assert documents["PW 1/2025"]["position_count"] == 2
    assert Decimal(documents["PW 1/2025"]["total_quantity"]) == Decimal("35")
    assert documents["PW 1/2025"]["warehouse_name"] == "Magazyn centralny"
    assert documents["PZ 1/2025"]["position_count"] == 1


def test_api_summary_counts_receipts(client, admin_headers, seeded_db) -> None:
    _sync(seeded_db)
    summary = client.get(
        "/api/v1/warehouse-documents/summary", headers=admin_headers
    ).json()
    assert summary["inbound_position_count"] == 3
    assert Decimal(summary["inbound_quantity"]) == Decimal("55")
    assert summary["inbound_unmapped_count"] == 0
    assert {entry["kind"] for entry in summary["by_kind"]} == {"PZ", "PW"}


def test_api_rebuild_requires_operator(client) -> None:
    assert client.post("/api/v1/warehouse-documents/rebuild-positions").status_code == 401
