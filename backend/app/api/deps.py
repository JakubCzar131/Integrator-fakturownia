from __future__ import annotations

from app.audit.service import readonly_violation_audit_callback
from app.database.session import SessionLocal
from app.services.fakturownia_client import FakturowniaClient


def build_fakturownia_client() -> FakturowniaClient:
    """Client factory with the read-only violation audit hook wired in."""
    return FakturowniaClient(
        audit_callback=readonly_violation_audit_callback(SessionLocal)
    )
