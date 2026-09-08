# Architektura

## Przegląd

System składa się z trzech kontenerów (docker-compose):

```
┌────────────┐     /api proxy      ┌──────────────┐   SQLAlchemy   ┌────────────┐
│  frontend   │ ─────────────────▶ │   backend     │ ─────────────▶ │ PostgreSQL │
│ React+nginx │                    │   FastAPI     │                │            │
└────────────┘                     └──────┬───────┘                └────────────┘
                                          │  wyłącznie GET (guard 3-warstwowy)
                                          ▼
                                   Fakturownia API
```

Fakturownia jest wyłącznie **źródłem danych** — jedyny komponent komunikujący
się z nią to `FakturowniaClient`, zablokowany technicznie do metody GET.

## Warstwy backendu

| Warstwa | Katalog | Odpowiedzialność |
|---|---|---|
| API | `app/api/routes/` | endpointy REST, walidacja wejścia, RBAC, audyt operacji |
| Serwisy (domena) | `app/services/` | logika biznesowa: sync, mapowanie, magazyn, walidacja, raporty |
| Modele | `app/models/` | schemat bazy (SQLAlchemy 2.0, typed mappings) |
| Schematy | `app/schemas/` | kontrakty API (Pydantic v2) |
| Infrastruktura | `app/database/`, `app/security/`, `app/logging_config.py` | sesje DB, JWT/bcrypt, maskowanie sekretów |
| Audyt | `app/audit/` | append-only `audit_log` |

Logika domenowa nie zależy od FastAPI — serwisy przyjmują `Session`
i obiekty domenowe, dzięki czemu testuje się je bez HTTP.

## Kluczowe przepływy

### Synchronizacja (`SyncService`)
1. `POST /sync/full` tworzy `SyncRun` i startuje wątek tła (mutex chroni przed
   równoległymi synchronizacjami; scheduler APS używa tej samej blokady).
2. Dla każdego zasobu: paginowane GET → snapshot JSON (`source_snapshots`,
   tylko przy zmianie hasha) → upsert do tabel mirror (`fakturownia_*`).
3. Post-processing: utworzenie lokalnych produktów (`products`) i automatyczne
   mapowanie pozycji faktur.
4. Wynik (liczniki, błędy, czas) zapisany w `sync_runs`.

### Magazyn (`StockService`)
Ledger jest **projekcją pochodną**: `rebuild_stock()` kasuje ledger i salda,
zbiera ruchy ze źródeł (stany początkowe, faktury, korekty ręczne, opcjonalnie
akcje magazynowe), sortuje deterministycznie (czas → priorytet) i odtwarza
salda z polami `balance_before/after`. Źródła są append-only — korekta błędu
to storno, nie kasowanie.

### Walidacja (`ValidationService`)
1. Przebudowa magazynu (żeby stany były aktualne).
2. Zbieranie problemów przez `_IssueCollector` (20 reguł).
3. Materializacja: upsert po `dedupe_key`, auto-RESOLVED dla nieaktualnych,
   respektowanie IGNORED, reopen dla nawrotów.

## Model danych (skrót)

* **Mirror Fakturowni:** `fakturownia_invoices(+positions)`, `fakturownia_products`,
  `fakturownia_clients`, `warehouses`, `warehouse_documents`, `warehouse_actions`,
  `fakturownia_categories/departments/payments/price_lists`,
  `fakturownia_product_stocks` (stany per magazyn raportowane przez Fakturownię).
* **Lokalny katalog:** `products`, `product_aliases`, `product_mappings`,
  `product_bundle_components`.
* **Magazyn lokalny:** `opening_balances`, `local_stock_adjustments`,
  `local_stock_ledger`, `local_stock_balances`.
* **Kontrola:** `validation_runs`, `validation_issues`, `validation_issue_comments`.
* **System:** `users`, `roles`, `user_roles`, `audit_log`, `sync_runs`,
  `source_snapshots`, `app_settings`, `saved_filters`,
  `table_column_preferences`, `report_exports`.

## Frontend

* React + TypeScript (Vite), bez ciężkich bibliotek UI — autorski design
  system w `src/components/erp/` + `src/components/datagrid/`.
* `DataGrid` obsługuje server-side sortowanie/paginację, wybór kolumn
  z zapisem preferencji per użytkownik (`table_column_preferences`).
* Moduły odpowiadają nawigacji ERP: Dashboard, Faktury, Pozycje, Klienci,
  Produkty, Mapowania, Magazyny, Stany, Ruchy, Walidacje, Raporty,
  Synchronizacja, Ustawienia, Użytkownicy, Audyt.
* Autoryzacja: JWT w localStorage, `AuthProvider` + role z backendu;
  przyciski zapisu ukryte dla roli `auditor`.

## Bezpieczeństwo

* JWT (PyJWT, HS256) + bcrypt; role: `admin`, `operator`, `auditor`.
* Wszystkie endpointy poza `/health` i `/auth/login` wymagają uwierzytelnienia;
  operacje zapisu wymagają roli `operator`/`admin`, zarządzanie użytkownikami
  i ustawieniami — `admin`.
* Sekrety tylko w env; `SecretMaskingFilter` maskuje token/hasła we wszystkich
  logach, a `mask_secrets()` w komunikatach wyjątków.
* Trójwarstwowy read-only guard dla Fakturowni + audyt prób zapisu.
