"""Shared fake data + fake Fakturownia client for sync/stock/validation tests."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any


FAKE_WAREHOUSES = [
    {"id": 900, "name": "Magazyn centralny", "kind": "main", "description": None},
]

FAKE_DEPARTMENTS = [{"id": 10, "name": "Firma Testowa Sp. z o.o.", "shortcut": "FT"}]

FAKE_CATEGORIES = [{"id": 20, "name": "Elektronika", "description": None}]

FAKE_PRODUCTS = [
    {
        "id": 101, "name": "Widget A", "code": "WID-A", "ean_code": "5901234567890",
        "quantity_unit": "szt", "tax": "23", "price_net": "100.00",
        "price_gross": "123.00", "currency": "PLN", "quantity": "50",
        "disabled": False,
    },
    {
        "id": 102, "name": "Widget B", "code": "WID-B", "ean_code": None,
        "quantity_unit": "szt", "tax": "23", "price_net": "10.00",
        "price_gross": "12.30", "currency": "PLN", "quantity": "5",
        "disabled": False,
    },
    {
        "id": 103, "name": "Usługa montażu", "code": "USL-M", "ean_code": None,
        "quantity_unit": "godz", "tax": "23", "price_net": "150.00",
        "price_gross": "184.50", "currency": "PLN", "quantity": None,
        "service": True, "disabled": False,
    },
]

FAKE_CLIENTS = [
    {"id": 501, "name": "Klient Pierwszy", "tax_no": "1111111111", "email": "k1@example.com",
     "city": "Warszawa", "street": "Prosta 1", "post_code": "00-001", "country": "PL"},
    {"id": 502, "name": "Klient Drugi", "tax_no": "2222222222", "email": "k2@example.com",
     "city": "Kraków", "street": "Długa 2", "post_code": "30-001", "country": "PL"},
]

FAKE_INVOICES = [
    {
        "id": 9001, "number": "FV 1/2025", "kind": "vat", "status": "paid",
        "income": True, "issue_date": "2025-01-10", "sell_date": "2025-01-10",
        "client_id": 501, "buyer_name": "Klient Pierwszy", "buyer_tax_no": "1111111111",
        "department_id": 10, "warehouse_id": 900, "currency": "PLN",
        "price_net": "1000.00", "price_gross": "1230.00", "paid": "1230.00",
        "updated_at": "2025-01-10T12:00:00Z",
        "positions": [
            {"id": 1, "product_id": 101, "name": "Widget A", "code": "WID-A",
             "quantity": "10", "quantity_unit": "szt", "price_net": "100.00",
             "price_gross": "123.00", "total_price_net": "1000.00",
             "total_price_gross": "1230.00", "tax": "23"},
        ],
    },
    {
        "id": 9002, "number": "FV 2/2025", "kind": "vat", "status": "issued",
        "income": True, "issue_date": "2025-01-15", "sell_date": "2025-01-15",
        "client_id": 502, "buyer_name": "Klient Drugi", "buyer_tax_no": "2222222222",
        "department_id": 10, "warehouse_id": 900, "currency": "PLN",
        "price_net": "120.00", "price_gross": "147.60", "paid": "0.00",
        "updated_at": "2025-01-15T09:00:00Z",
        "positions": [
            # No product_id — must be resolved through mapping (name matches Widget B).
            {"id": 2, "product_id": None, "name": "Widget B", "code": "WID-B",
             "quantity": "12", "quantity_unit": "szt", "price_net": "10.00",
             "price_gross": "12.30", "total_price_net": "120.00",
             "total_price_gross": "147.60", "tax": "23"},
        ],
    },
    {
        "id": 9003, "number": "FV 3/2025", "kind": "vat", "status": "issued",
        "income": True, "issue_date": "2025-01-20", "sell_date": "2025-01-20",
        "client_id": 501, "buyer_name": "Klient Pierwszy", "buyer_tax_no": "1111111111",
        "department_id": 10, "warehouse_id": 900, "currency": "PLN",
        "price_net": "150.00", "price_gross": "184.50", "paid": "184.50",
        "updated_at": "2025-01-20T15:00:00Z",
        "positions": [
            {"id": 3, "product_id": 103, "name": "Usługa montażu", "code": "USL-M",
             "quantity": "1", "quantity_unit": "godz", "price_net": "150.00",
             "price_gross": "184.50", "total_price_net": "150.00",
             "total_price_gross": "184.50", "tax": "23"},
            # Completely unknown position name — should stay unmapped.
            {"id": 4, "product_id": None, "name": "Tajemniczy gadżet XYZ", "code": None,
             "quantity": "2", "quantity_unit": "szt", "price_net": "20.00",
             "price_gross": "24.60", "total_price_net": "40.00",
             "total_price_gross": "49.20", "tax": "23"},
        ],
    },
    {
        # Correction to FV 1/2025: return of 2 pieces of Widget A.
        "id": 9004, "number": "KOR 1/2025", "kind": "correction", "status": "issued",
        "income": True, "issue_date": "2025-02-01", "sell_date": "2025-02-01",
        "client_id": 501, "buyer_name": "Klient Pierwszy",
        "from_invoice_id": 9001, "warehouse_id": 900, "currency": "PLN",
        "price_net": "-200.00", "price_gross": "-246.00", "paid": "0.00",
        "updated_at": "2025-02-01T10:00:00Z",
        "positions": [
            {"id": 5, "product_id": 101, "name": "Widget A", "code": "WID-A",
             "quantity": "-2", "quantity_unit": "szt", "price_net": "100.00",
             "price_gross": "123.00", "total_price_net": "-200.00",
             "total_price_gross": "-246.00", "tax": "23"},
        ],
    },
    {
        # Cancelled invoice — must not settle stock.
        "id": 9005, "number": "FV 4/2025", "kind": "vat", "status": "cancelled",
        "cancelled": True, "income": True,
        "issue_date": "2025-02-05", "sell_date": "2025-02-05",
        "client_id": 502, "buyer_name": "Klient Drugi", "warehouse_id": 900,
        "currency": "PLN", "price_net": "500.00", "price_gross": "615.00",
        "paid": "0.00", "updated_at": "2025-02-05T10:00:00Z",
        "positions": [
            {"id": 6, "product_id": 101, "name": "Widget A", "code": "WID-A",
             "quantity": "5", "quantity_unit": "szt", "price_net": "100.00",
             "price_gross": "123.00", "total_price_net": "500.00",
             "total_price_gross": "615.00", "tax": "23"},
        ],
    },
]

FAKE_WAREHOUSE_DOCUMENTS = [
    {"id": 7001, "kind": "PZ", "number": "PZ 1/2025", "warehouse_id": 900,
     "issue_date": "2025-01-02", "client_id": None, "invoice_id": None,
     "description": "Dostawa początkowa"},
]

FAKE_WAREHOUSE_ACTIONS = [
    {"id": 8001, "warehouse_document_id": 7001, "warehouse_id": 900,
     "product_id": 101, "kind": "PZ", "quantity": "20", "price_net": "80.00",
     "created_at": "2025-01-02T08:00:00Z"},
]

FAKE_PAYMENTS = [
    {"id": 601, "name": "Płatność FV 1/2025", "price": "1230.00", "currency": "PLN",
     "paid_date": "2025-01-12", "invoice_id": 9001, "invoice_ids": [9001]},
]

FAKE_PRICE_LISTS = [{"id": 701, "name": "Cennik podstawowy", "currency": "PLN"}]


class FakeFakturowniaClient:
    """In-memory stand-in for the read-only Fakturownia client."""

    def __init__(
        self,
        invoices: list[dict[str, Any]] | None = None,
        products: list[dict[str, Any]] | None = None,
    ) -> None:
        self.invoices = invoices if invoices is not None else FAKE_INVOICES
        self.products = products if products is not None else FAKE_PRODUCTS
        self.requested_methods: list[str] = []

    def get_departments(self) -> list[dict[str, Any]]:
        return FAKE_DEPARTMENTS

    def get_categories(self) -> list[dict[str, Any]]:
        return FAKE_CATEGORIES

    def get_warehouses(self) -> list[dict[str, Any]]:
        return FAKE_WAREHOUSES

    def iter_products(self, warehouse_id: int | None = None) -> Iterator[list[dict[str, Any]]]:
        if warehouse_id is not None:
            yield [
                {**prod, "quantity": prod.get("quantity")}
                for prod in self.products
                if prod.get("quantity") is not None
            ]
            return
        yield self.products

    def iter_clients(self) -> Iterator[list[dict[str, Any]]]:
        yield FAKE_CLIENTS

    def iter_invoices(self, period: str = "all", **extra: Any) -> Iterator[list[dict[str, Any]]]:
        yield self.invoices

    def iter_warehouse_documents(self) -> Iterator[list[dict[str, Any]]]:
        yield FAKE_WAREHOUSE_DOCUMENTS

    def iter_warehouse_actions(self) -> Iterator[list[dict[str, Any]]]:
        yield FAKE_WAREHOUSE_ACTIONS

    def iter_payments(self) -> Iterator[list[dict[str, Any]]]:
        yield FAKE_PAYMENTS

    def get_price_lists(self) -> list[dict[str, Any]]:
        return FAKE_PRICE_LISTS
