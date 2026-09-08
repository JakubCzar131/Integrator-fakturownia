"""Normalization of warehouse document positions (PZ / PW and friends).

Fakturownia exposes goods receipts as ``warehouse_documents``.  Depending on
the account, the individual lines arrive either embedded in the document
payload (``positions`` / ``items`` / ``warehouse_actions``) or only as separate
``warehouse_actions`` records.  Both shapes are folded into
``warehouse_document_positions`` so that receipts can be aggregated with plain
SQL instead of digging through JSON on every request.

Everything here reads from the local mirror only — no API traffic.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.enums import WarehouseDocumentKind
from app.models.fakturownia import (
    WarehouseAction,
    WarehouseDocument,
    WarehouseDocumentPosition,
)
from app.services import parsing as p

logger = logging.getLogger(__name__)

POSITION_KEYS = ("positions", "warehouse_actions", "items", "warehouse_document_positions")

_KIND_ALIASES = {
    "pz": WarehouseDocumentKind.PZ,
    "pw": WarehouseDocumentKind.PW,
    "wz": WarehouseDocumentKind.WZ,
    "rw": WarehouseDocumentKind.RW,
    "mm": WarehouseDocumentKind.MM,
    "mm_in": WarehouseDocumentKind.MM,
    "mm_out": WarehouseDocumentKind.MM,
    "zw": WarehouseDocumentKind.ZW,
}


def normalize_document_kind(raw_kind: str | None) -> str:
    """Map a Fakturownia document/action kind onto our canonical kind."""
    key = (raw_kind or "").strip().lower()
    if not key:
        return str(WarehouseDocumentKind.OTHER)
    matched = _KIND_ALIASES.get(key)
    if matched is None:
        # Kinds occasionally arrive suffixed, e.g. "pz_correction".
        for alias, kind in _KIND_ALIASES.items():
            if key.startswith(alias):
                matched = kind
                break
    return str(matched or WarehouseDocumentKind.OTHER)


def extract_position_payloads(
    document: WarehouseDocument, actions: list[WarehouseAction]
) -> list[dict[str, Any]]:
    """Return the position payloads for a document, embedded ones taking priority."""
    raw = document.raw or {}
    for key in POSITION_KEYS:
        value = raw.get(key)
        if isinstance(value, list) and value:
            return [item for item in value if isinstance(item, dict)]
    return [action.raw or _action_as_payload(action) for action in actions]


def _action_as_payload(action: WarehouseAction) -> dict[str, Any]:
    return {
        "id": action.fakturownia_id,
        "product_id": action.product_fakturownia_id,
        "kind": action.kind,
        "quantity": str(action.quantity) if action.quantity is not None else None,
        "price_net": str(action.price_net) if action.price_net is not None else None,
        "warehouse_id": action.warehouse_fakturownia_id,
    }


def rebuild_document_positions(db: Session) -> dict[str, Any]:
    """(Re)build normalized positions for every mirrored warehouse document."""
    actions_by_document: dict[int, list[WarehouseAction]] = {}
    for action in db.execute(
        select(WarehouseAction).where(WarehouseAction.is_deleted_upstream.is_(False))
    ).scalars():
        if action.warehouse_document_fakturownia_id is not None:
            actions_by_document.setdefault(
                action.warehouse_document_fakturownia_id, []
            ).append(action)

    stats = {"documents": 0, "rebuilt": 0, "unchanged": 0, "positions": 0, "inbound_positions": 0}
    documents = db.execute(
        select(WarehouseDocument).where(WarehouseDocument.is_deleted_upstream.is_(False))
    ).scalars().all()

    for document in documents:
        stats["documents"] += 1
        payloads = extract_position_payloads(
            document, actions_by_document.get(document.fakturownia_id, [])
        )
        signature = p.payload_hash(
            {"kind": document.kind, "issue_date": str(document.issue_date), "positions": payloads}
        )
        if signature == document.positions_built_hash:
            stats["unchanged"] += 1
            continue

        # An ORM-level delete keeps the identity map and the ``positions``
        # collection in step with the database; a Core-level delete would leave
        # the session serving the rows it just removed.
        db.execute(
            delete(WarehouseDocumentPosition).where(
                WarehouseDocumentPosition.document_id == document.id
            )
        )
        db.expire(document, ["positions"])
        kind = normalize_document_kind(document.kind)
        for payload in payloads:
            position = _build_position(document, kind, payload)
            db.add(position)
            stats["positions"] += 1
            if kind in (str(WarehouseDocumentKind.PZ), str(WarehouseDocumentKind.PW)):
                stats["inbound_positions"] += 1
        document.positions_built_hash = signature
        stats["rebuilt"] += 1

    db.flush()
    return stats


def _build_position(
    document: WarehouseDocument, kind: str, payload: dict[str, Any]
) -> WarehouseDocumentPosition:
    position_kind = kind
    # A position may carry its own kind (typical for action-derived payloads).
    if payload.get("kind"):
        derived = normalize_document_kind(str(payload.get("kind")))
        if derived != str(WarehouseDocumentKind.OTHER):
            position_kind = derived
    return WarehouseDocumentPosition(
        document_id=document.id,
        document_kind=position_kind,
        fakturownia_id=p.to_int(payload.get("id")),
        source_action_fakturownia_id=p.to_int(
            payload.get("warehouse_action_id") or payload.get("id")
        ),
        product_fakturownia_id=p.to_int(payload.get("product_id")),
        name=p.to_str(payload.get("name") or payload.get("product_name"), 1000),
        code=p.to_str(payload.get("code") or payload.get("product_code"), 255),
        quantity=p.to_decimal(payload.get("quantity")),
        quantity_unit=p.to_str(payload.get("quantity_unit") or payload.get("unit"), 50),
        purchase_price_net=p.to_decimal(
            payload.get("purchase_price_net")
            or payload.get("price_net")
            or payload.get("purchase_price")
        ),
        issue_date=document.issue_date,
        warehouse_fakturownia_id=(
            p.to_int(payload.get("warehouse_id")) or document.warehouse_fakturownia_id
        ),
        raw=payload,
    )
