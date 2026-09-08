# Lokalne API REST

Baza: `http://localhost:8000/api/v1` (Swagger: `/api/docs`,
OpenAPI: `/api/openapi.json`).

Uwierzytelnianie: `POST /auth/login` (OAuth2 password flow) → JWT Bearer.
Role: `admin` (wszystko), `operator` (operacje lokalne), `auditor` (odczyt).

Endpointy `POST`/`PATCH`/`PUT`/`DELETE` zapisują **wyłącznie lokalną bazę** —
żaden z nich nie powoduje zapisu do Fakturowni.

## Systemowe

| Metoda | Ścieżka | Rola | Opis |
|---|---|---|---|
| GET | `/health` | — | status aplikacji i bazy |
| POST | `/auth/login` | — | logowanie (form: username, password) |
| GET | `/auth/me` | każdy | dane zalogowanego użytkownika |
| GET | `/dashboard` | auditor+ | KPI, ostatnia synchronizacja/walidacja |

## Synchronizacja

| Metoda | Ścieżka | Rola | Opis |
|---|---|---|---|
| POST | `/sync/full` | operator | pełna synchronizacja (w tle; tylko GET do Fakturowni) |
| POST | `/sync/incremental` | operator | synchronizacja przyrostowa |
| GET | `/sync/runs` | auditor+ | historia z paginacją i filtrami |
| GET | `/sync/status` | auditor+ | bieżący stan + ostatni sukces |

## Dane z Fakturowni (odczyt lokalnego mirroru)

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET | `/invoices` | lista faktur; filtry: `search,number,buyer,kind,invoice_status,validation,product_id,date_from,date_to`; sortowanie `sort_by/sort_dir` |
| GET | `/invoices/{id}` | szczegół z pozycjami i surowym JSON |
| GET | `/invoices/{id}/issues` | problemy walidacyjne faktury |
| GET | `/invoices/{id}/ledger` | ruchy magazynowe faktury |
| GET | `/invoice-positions` | globalna lista pozycji; filtry: `search,mapping_status,product_id,invoice_id` |
| GET | `/clients` | klienci |

## Produkty i mapowania (zapis lokalny)

| Metoda | Ścieżka | Rola | Opis |
|---|---|---|---|
| GET | `/products` | auditor+ | lista z lokalnym stanem, stanem Fakturowni i licznikami problemów |
| GET | `/products/{id}` | auditor+ | karta produktu (aliasy, skład zestawu) |
| PATCH | `/products/{id}` | operator | lokalna klasyfikacja: `kind,is_stock_controlled,is_active,unit,notes` |
| POST | `/products/aliases` | operator | alias (NAME/CODE/EAN/SKU/UNIT) |
| DELETE | `/products/aliases/{id}` | operator | usunięcie aliasu (audytowane) |
| PUT | `/products/{id}/bundle` | operator | skład zestawu |
| GET | `/product-mappings` | auditor+ | mapowania (filtry status/search, liczba wystąpień) |
| POST | `/product-mappings` | operator | ręczne mapowanie sygnatury → produkt |
| PATCH | `/product-mappings/{id}` | operator | zatwierdzenie/odrzucenie/zmiana; auto-przeliczenie pozycji |
| POST | `/product-mappings/reapply` | operator | ponowne zastosowanie mapowań |

## Magazyn (zapis lokalny)

| Metoda | Ścieżka | Rola | Opis |
|---|---|---|---|
| GET | `/warehouses` | auditor+ | magazyny + liczniki stanów |
| GET | `/stock/balances` | auditor+ | salda; filtry: `search,warehouse_id,product_id,only_negative,only_discrepancies` |
| GET | `/stock/ledger` | auditor+ | ledger; filtry: `product_id,warehouse_id,movement_type,invoice_id` |
| GET/POST | `/stock/opening-balances` | operator (POST) | stany początkowe |
| GET/POST | `/stock/local-adjustments` | operator (POST) | korekty lokalne |
| POST | `/stock/local-adjustments/{id}/reverse` | operator | storno korekty |
| POST | `/stock/recalculate` | operator | przebudowa ledgera i sald |

## Walidacja

| Metoda | Ścieżka | Rola | Opis |
|---|---|---|---|
| POST | `/validation/run` | operator | uruchomienie walidacji (z przebudową stanów) |
| GET | `/validation/runs` | auditor+ | historia uruchomień |
| GET | `/validation/issues` | auditor+ | problemy; filtry: `status` (lista po przecinku), `issue_type,severity,invoice_id,product_id,warehouse_id,search` |
| GET | `/validation/issues/summary` | auditor+ | agregaty po statusie i typie |
| GET | `/validation/issues/{id}` | auditor+ | szczegół z komentarzami |
| PATCH | `/validation/issues/{id}` | operator | zmiana statusu (lokalnie) |
| POST | `/validation/issues/{id}/comments` | operator | komentarz (lokalnie) |

## Raporty

`GET /reports/{key}?format=json|csv|xlsx|pdf` — klucze: `sales`
(`date_from`,`date_to`), `unmapped-products`, `negative-stock`,
`stock-discrepancies`, `stock-history` (`product_id`,`warehouse_id`),
`problem-invoices`, `top-error-products`. Eksporty są logowane
w `report_exports` i audycie.

## Administracja

| Metoda | Ścieżka | Rola | Opis |
|---|---|---|---|
| GET | `/audit-log` | auditor+ | audyt; filtry: `action,object_type,user_email,date_from,date_to` |
| GET | `/settings` | każdy | ustawienia + status konfiguracji Fakturowni (**bez tokenu**) |
| PATCH | `/settings` | admin | zmiana ustawień lokalnych |
| GET | `/settings/column-preferences/{table}` | każdy | preferencje kolumn użytkownika |
| PUT | `/settings/column-preferences` | każdy | zapis preferencji kolumn |
| GET/POST | `/users` | admin | lista/tworzenie użytkowników |
| PATCH | `/users/{id}` | admin | edycja, role, aktywność, hasło |
| GET | `/users/roles` | admin | dostępne role |

## Paginacja list

Wszystkie listy zwracają kopertę:

```json
{ "items": [...], "total": 123, "page": 1, "per_page": 50, "pages": 3 }
```

Parametry: `page`, `per_page` (≤500), `sort_by`, `sort_dir=asc|desc`.
