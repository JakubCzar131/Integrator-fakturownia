# Plan rozbudowy: konfiguracja dynamiczna, rozliczenie PZ/PW, integracja SkyShop

Status: **projekt architektury / plan implementacji** (do akceptacji przed kodowaniem).

Dokument opisuje wdrożenie trzech modułów do istniejącego systemu WMS Kontrola:

1. dynamiczna konfiguracja danych dostępowych (Fakturownia, docelowo każdy provider) w bazie + UI,
2. rozbudowa gospodarki magazynowej o dokumenty PZ/PW i **Tabelę Rozliczeniową**,
3. dwukierunkowa integracja z **SkyShop WebAPI** (synchronizacja stanów + PIM).

## 0. Kontekst i granice bezpieczeństwa

* Obecny system ma **twardy read-only guard wobec Fakturowni** — to się **nie zmienia**.
  Moduł 2 nadal używa wyłącznie GET (PZ/PW pobieramy, niczego nie tworzymy).
* Zapis wychodzący pojawia się wyłącznie w kierunku **SkyShop** i dostaje własny,
  odseparowany klient (`SkyShopClient`) z pełnym audytem każdej mutacji,
  globalnym kill-switchem i trybem dry-run. Guard Fakturowni i klient SkyShop
  to fizycznie różne klasy — nie ma możliwości pomylenia kierunków zapisu.
* Fakty o SkyShop WebAPI (potwierdzone w dokumentacji platformy):
  * endpoint per sklep: `https://{domena-sklepu}/api` (dokumentacja + sandbox pod tym adresem),
  * autoryzacja kluczem WebAPI (panel: Integracje → Web API sklepu; możliwych wiele kluczy),
  * metody GET i POST,
  * **limit: 1 zapytanie / sekundę** — architektura musi być kolejkowa i delta-owa.

---

## Moduł 1 — konfiguracja integracji w bazie + UI

### 1.1. Model danych (nowa tabela `integration_accounts`)

```sql
CREATE TABLE integration_accounts (
    id              SERIAL PRIMARY KEY,
    provider        VARCHAR(30) NOT NULL,          -- 'FAKTUROWNIA' | 'SKYSHOP'
    label           VARCHAR(255) NOT NULL,         -- np. "Konto główne", "Sklep outdoor.pl"
    config          JSONB NOT NULL DEFAULT '{}',   -- dane NIE-sekretne: domena/base_url, per_page, rate limit
    secret_encrypted BYTEA,                        -- token/klucz API zaszyfrowany Fernet (AES + HMAC)
    secret_hint     VARCHAR(12),                   -- ostatnie 4 znaki do identyfikacji w UI
    is_active       BOOLEAN NOT NULL DEFAULT true,
    verified_at     TIMESTAMPTZ,                   -- ostatni udany test połączenia
    verified_status VARCHAR(20),                   -- OK | FAILED | NEVER
    verified_error  TEXT,
    created_by_user_id INT REFERENCES users(id) ON DELETE SET NULL,
    updated_by_user_id INT REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, label)
);
```

Zasady bezpieczeństwa:

* Sekret szyfrowany **Fernet** (biblioteka `cryptography`); klucz główny
  `INTEGRATION_MASTER_KEY` pozostaje **wyłącznie w env** — kompromitacja dumpa
  bazy nie ujawnia tokenów.
* API nigdy nie zwraca sekretu — tylko `secret_configured: true` + `secret_hint`.
* Wpis/zmiana sekretu audytowana **bez wartości** (stary/nowy hint).
* Maskowanie logów rozszerzone: `SecretMaskingFilter` dostaje dynamiczną listę
  sekretów z providera konfiguracji (dziś czyta tylko env).

### 1.2. Warstwa dostępu: `IntegrationConfigService`

Nowy serwis `app/services/integration_config.py`:

* `get_fakturownia_config() -> FakturowniaConfig` / `get_skyshop_config() -> SkyShopConfig`,
* kolejność źródeł: **baza (aktywny wpis) → fallback do env** (pełna kompatybilność
  wsteczna z obecnym `.env`; istniejące instalacje działają bez migracji ręcznej),
* cache w pamięci procesu z inwalidacją po każdym zapisie (timestamp w `app_settings`
  `integration_config_version` — działa też przy wielu workerach uvicorn),
* jedyny punkt wymiany: `build_fakturownia_client()` w `app/api/deps.py` przechodzi
  z `get_settings()` na `IntegrationConfigService` — reszta kodu bez zmian.

### 1.3. Endpointy i UI

| Metoda | Ścieżka | Rola | Opis |
|---|---|---|---|
| GET | `/settings/integrations` | admin | lista kont (bez sekretów) |
| POST | `/settings/integrations` | admin | nowe konto (provider, label, config, secret) |
| PATCH | `/settings/integrations/{id}` | admin | edycja; sekret opcjonalny (puste = bez zmian) |
| POST | `/settings/integrations/{id}/test-connection` | admin | test na żywo: Fakturownia → `GET /departments.json`; SkyShop → lekki odczyt z `/api` |
| DELETE | `/settings/integrations/{id}` | admin | dezaktywacja (soft; audytowana) |

UI: nowa zakładka **„Integracje”** w istniejącym module Ustawienia — karta per
provider, formularz z polem sekretu typu password, przycisk „Testuj połączenie”,
badge statusu weryfikacji, hint `••••abcd`.

---

## Moduł 2 — dokumenty PZ/PW i Tabela Rozliczeniowa

### 2.1. Co już mamy, co dochodzi

Sync już dziś pobiera `warehouse_documents` i `warehouse_actions` (GET).
Dochodzi normalizacja **pozycji dokumentów** (dziś pozycje siedzą w `raw` JSON):

```sql
CREATE TABLE warehouse_document_positions (
    id              SERIAL PRIMARY KEY,
    document_id     INT NOT NULL REFERENCES warehouse_documents(id) ON DELETE CASCADE,
    document_kind   VARCHAR(20),                -- PZ | PW | WZ | RW | MM (denormalizacja pod agregaty)
    fakturownia_id  BIGINT UNIQUE,
    product_fakturownia_id BIGINT,
    mapped_product_id INT REFERENCES products(id) ON DELETE SET NULL,  -- ten sam pipeline mapowania co pozycje faktur
    name            VARCHAR(1000),
    code            VARCHAR(255),
    quantity        NUMERIC(18,4),
    purchase_price_net NUMERIC(18,2),
    issue_date      DATE,                       -- z nagłówka dokumentu (denormalizacja pod agregaty)
    warehouse_fakturownia_id BIGINT,
    raw             JSONB
);
CREATE INDEX ix_wdp_product_kind ON warehouse_document_positions (mapped_product_id, document_kind);
CREATE INDEX ix_wdp_issue_date ON warehouse_document_positions (issue_date);
```

Zasilanie: krok syncu parsuje `raw` dokumentów (a `warehouse_actions` służą jako
źródło uzupełniające, jeśli payload dokumentu nie zawiera pozycji). Pozycje
przechodzą przez istniejący `mapping_service` (product_id → mapowanie → alias →
kod → EAN → nazwa), więc PZ/PW korzystają z tego samego panelu mapowań co faktury.

### 2.2. Tabela Rozliczeniowa — model wyliczeń

Kluczowa zasada optymalizacyjna: **rozliczenie liczy się w 100% z lokalnego
mirroru — zero zapytań do zewnętrznych API w momencie renderowania**. Jedyne
zapytania zewnętrzne wykonuje istniejący sync (raz na cykl), który już dziś
pobiera wszystkie potrzebne dane.

Wiersz rozliczenia per **produkt × magazyn**:

| Kolumna | Źródło (lokalne) |
|---|---|
| Stan wg Fakturowni | `fakturownia_product_stocks` (per magazyn) lub `fakturownia_products.quantity` |
| Σ przyjęć PZ | `warehouse_document_positions` (kind='PZ') |
| Σ przyjęć PW | `warehouse_document_positions` (kind='PW') |
| Σ rozchodów z faktur | `fakturownia_invoice_positions` × `fakturownia_invoices` (sale_kinds, bez anulowanych) |
| Σ korekt faktur | jw., kind='correction' (delta ujemna = zwrot) |
| Stan początkowy (lokalny) | `opening_balances` (opcjonalny składnik) |
| **Stan wyliczony** | `opening + ΣPZ + ΣPW − Σsprzedaż + Σkorekty` |
| **Różnica** | `stan_wyliczony − stan_Fakturownia` |
| Status spójności | `OK` (|diff| ≤ tolerancja) / `DISCREPANCY` |

Uwaga architektoniczna: to jest **warstwa raportowa, niezależna od ledgera**.
Ledger (kontrola operacyjna) nadal liczy stany wg swojej konfiguracji; Tabela
Rozliczeniowa to równoległe zestawienie „dokumentowe” (Fakturownia vs PZ/PW vs
faktury), którego celem jest wykrycie niespójności między trzema źródłami.
Dzięki temu unikamy podwójnego liczenia przyjęć w ledgerze.

### 2.3. Materializacja (wydajność przy dużych wolumenach)

Snapshot zamiast liczenia ad-hoc:

```sql
CREATE TABLE stock_reconciliation_lines (
    id              BIGSERIAL PRIMARY KEY,
    run_id          INT NOT NULL,                 -- FK do sync_runs / własne reconciliation_runs
    product_id      INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    warehouse_id    INT REFERENCES warehouses(id) ON DELETE CASCADE,
    fakturownia_stock NUMERIC(18,4),
    inbound_pz      NUMERIC(18,4) NOT NULL DEFAULT 0,
    inbound_pw      NUMERIC(18,4) NOT NULL DEFAULT 0,
    sold_invoices   NUMERIC(18,4) NOT NULL DEFAULT 0,
    corrections     NUMERIC(18,4) NOT NULL DEFAULT 0,
    opening_balance NUMERIC(18,4),
    computed_stock  NUMERIC(18,4) NOT NULL,
    difference      NUMERIC(18,4),
    status          VARCHAR(20) NOT NULL,         -- OK | DISCREPANCY | NO_REMOTE_STOCK
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, product_id, warehouse_id)
);
```

* Przeliczenie: **3–4 agregujące zapytania SQL** (GROUP BY product/warehouse)
  + złączenie w pamięci — dla dziesiątek tysięcy produktów czas rzędu sekund.
* Trigger przeliczenia: automatycznie po każdym syncu (hook w `SyncService._run`)
  + ręcznie `POST /reconciliation/refresh`.
* Historia run-ów zostaje → trend różnic w czasie (kiedy pojawiła się rozbieżność).
* UI czyta zawsze ostatni snapshot: paginacja/sortowanie/filtry po indeksowanej tabeli.

### 2.4. Endpointy i UI

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET | `/reconciliation` | ostatni snapshot; filtry: `search`, `warehouse_id`, `status`, `only_discrepancies`; paginacja/sort |
| GET | `/reconciliation/runs` | historia przeliczeń |
| POST | `/reconciliation/refresh` | ręczne przeliczenie (operator) |
| GET | `/reconciliation?format=csv|xlsx` | eksport (istniejący silnik eksportów) |

UI: nowy moduł **„Rozliczenie dokumentów”** w sekcji Magazyn (istniejący
`DataGrid` — kolumny jak w tabeli wyżej, czerwone podświetlenie różnic,
przejście z wiersza do karty produktu i listy dokumentów PZ/PW).

---

## Moduł 3 — SkyShop (stany + PIM, podejście headless)

### 3.1. Klient `SkyShopClient` (`app/services/skyshop_client.py`)

* Konfiguracja z `integration_accounts` (URL sklepu + klucz WebAPI).
* **Rate limiter 1 rps** wbudowany w klienta (limit platformy — twardy).
* Retry z backoffem na 429/5xx/timeout; klucz maskowany w logach.
* Bezpieczniki dla zapisu:
  * `skyshop_sync_enabled` (app_settings) — globalny kill-switch,
  * `skyshop_dry_run` — pełny przebieg z logowaniem payloadów bez wysyłki,
  * audyt **każdej** mutacji (`SKYSHOP_WRITE`) z payloadem i odpowiedzią.
* Szczegółowe nazwy metod API są per sklep (dokumentacja pod `https://{domena}/api`)
  — klient dostaje cienką warstwę adaptera, więc doprecyzowanie sygnatur po
  otrzymaniu dostępu do sklepu nie zmienia architektury.

### 3.2. Model danych

```sql
-- Mirror produktów SkyShop (odczyt; odświeżany cyklicznie i przed weryfikacją)
CREATE TABLE skyshop_products (
    id              SERIAL PRIMARY KEY,
    skyshop_id      VARCHAR(64) UNIQUE NOT NULL,
    sku             VARCHAR(255), ean VARCHAR(64), name VARCHAR(1000),
    price_gross     NUMERIC(18,2), quantity NUMERIC(18,4),
    category_skyshop_id VARCHAR(64), is_active BOOLEAN,
    raw JSONB, payload_hash VARCHAR(64), last_synced_at TIMESTAMPTZ
);
CREATE TABLE skyshop_categories (
    id SERIAL PRIMARY KEY, skyshop_id VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(500), parent_skyshop_id VARCHAR(64), path TEXT, raw JSONB
);

-- Powiązanie produkt lokalny <-> produkt SkyShop (serce integracji)
CREATE TABLE skyshop_product_links (
    id              SERIAL PRIMARY KEY,
    product_id      INT UNIQUE NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    skyshop_id      VARCHAR(64),
    status          VARCHAR(20) NOT NULL DEFAULT 'MISSING',
                    -- LINKED | MISSING | AMBIGUOUS | EXCLUDED | PENDING_CREATE
    match_type      VARCHAR(20),                  -- SKU | EAN | MANUAL
    last_pushed_stock NUMERIC(18,4),              -- delta-push: co ostatnio wysłaliśmy
    last_pushed_content_hash VARCHAR(64),         -- hash payloadu PIM (opis/zdjęcia/atrybuty)
    last_pushed_at  TIMESTAMPTZ,
    last_error      TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Dane PIM utrzymywane lokalnie (source of truth dla SkyShop)
CREATE TABLE product_contents (
    product_id      INT PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
    description_html TEXT,
    short_description TEXT,
    images          JSONB NOT NULL DEFAULT '[]',   -- [{url|path, alt, position}]
    attributes      JSONB NOT NULL DEFAULT '{}',   -- {"Kolor":"czerwony", ...}
    price_gross     NUMERIC(18,2), vat_rate VARCHAR(10),
    local_category_id INT,
    updated_by_user_id INT REFERENCES users(id) ON DELETE SET NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Mapowanie kategorii lokalnych -> SkyShop
CREATE TABLE skyshop_category_mappings (
    id SERIAL PRIMARY KEY,
    local_category_id INT NOT NULL,
    skyshop_category_id VARCHAR(64) NOT NULL,
    UNIQUE (local_category_id)
);
```

### 3.3. Kolejka zadań — outbox w PostgreSQL + worker APScheduler

```sql
CREATE TABLE sync_jobs (
    id              BIGSERIAL PRIMARY KEY,
    provider        VARCHAR(30) NOT NULL,          -- 'SKYSHOP' (otwarte na kolejne)
    job_type        VARCHAR(40) NOT NULL,
        -- SKYSHOP_STOCK_PUSH | SKYSHOP_PRODUCT_CREATE | SKYSHOP_PRODUCT_UPDATE
        -- | SKYSHOP_MIRROR_REFRESH | SKYSHOP_IMAGE_UPLOAD
    dedupe_key      VARCHAR(120),                  -- np. 'stock:product:123'
    payload         JSONB NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                    -- PENDING | RUNNING | SUCCESS | FAILED | CANCELLED
    priority        SMALLINT NOT NULL DEFAULT 5,
    attempts        SMALLINT NOT NULL DEFAULT 0,
    max_attempts    SMALLINT NOT NULL DEFAULT 5,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ, finished_at TIMESTAMPTZ,
    result          JSONB, last_error TEXT,
    created_by_user_id INT REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_sync_jobs_pickup ON sync_jobs (status, next_attempt_at, priority);
CREATE UNIQUE INDEX uq_sync_jobs_dedupe_pending ON sync_jobs (dedupe_key)
    WHERE status IN ('PENDING','RUNNING');
```

Worker (`app/services/sync_worker.py`):

* pętla APScheduler co ~2 s: `SELECT … FOR UPDATE SKIP LOCKED` → batch jobów,
* wykonanie przez `SkyShopClient` (rate limiter i tak dławi do 1 rps),
* sukces → `SUCCESS` + result; błąd → backoff wykładniczy, po `max_attempts`
  status `FAILED` (dead-letter widoczny w UI z przyciskiem „Ponów”),
* **deduplikacja**: częściowy indeks unikalny sprawia, że wielokrotne zlecenie
  push-u stanu tego samego produktu nadpisuje payload oczekującego joba zamiast
  mnożyć wpisy — przy limicie 1 rps to kluczowe.

Dlaczego nie Celery+Redis od razu: wąskim gardłem jest limit 1 rps po stronie
SkyShop, nie przepustowość workera; outbox w PostgreSQL daje trwałość,
transakcyjność z resztą danych (job dopisywany w tej samej transakcji co zmiana
stanu) i zero nowych komponentów infrastruktury. Model tabeli jest zgodny z
przejściem na Celery w przyszłości — zmienia się tylko konsument.

### 3.4. Synchronizacja stanów (minimalizacja zapytań)

Przepływ cyklu (CRON w istniejącym schedulerze):

```
sync Fakturownia (GET) → rebuild ledger → snapshot rozliczenia
      → delta-detect → enqueue SKYSHOP_STOCK_PUSH (tylko zmienione) → worker 1 rps
```

* Po każdym przeliczeniu stanów porównujemy stan wyliczony z
  `skyshop_product_links.last_pushed_stock` — **enqueue tylko dla różnic**.
  Stabilny asortyment = niemal zero zapytań do SkyShop.
* Jeżeli dokumentacja sklepu udostępnia operacje masowe (aktualizacja wielu
  pozycji jednym POST), worker skleja PENDING joby stanów w paczki → dalsza
  redukcja liczby wywołań.
* Źródło stanu do wysyłki: konfigurowalne (`skyshop_stock_source`):
  `LOCAL_LEDGER` (domyślnie) | `FAKTUROWNIA` | `RECONCILED`.

### 3.5. PIM — weryfikacja i publikacja produktów

* **Weryfikacja obecności**: `SKYSHOP_MIRROR_REFRESH` pobiera produkty sklepu do
  mirroru; matcher (analogiczny do istniejącego `mapping_service`) łączy po
  SKU → EAN → ręcznie; wynik w `skyshop_product_links.status`
  (LINKED / MISSING / AMBIGUOUS). Weryfikacja odbywa się **na mirrorze, nie
  odpytując API per produkt**.
* **Publikacja**: pojedynczo (karta produktu → „Wyślij do SkyShop”) lub masowo
  (zaznaczenie w gridzie → `SKYSHOP_PRODUCT_CREATE` per produkt, kolejka dławi
  tempo). Payload budowany z `products` + `product_contents` +
  `skyshop_category_mappings`; zdjęcia jako osobne joby `SKYSHOP_IMAGE_UPLOAD`
  zależne od utworzenia produktu.
* **Aktualizacje**: `last_pushed_content_hash` — publikujemy tylko gdy hash
  treści PIM się zmienił (ten sam wzorzec delta co przy stanach).
* Walidacje przed enqueue: produkt aktywny, ma cenę, zmapowaną kategorię,
  komplet danych — braki raportowane w UI zanim cokolwiek pójdzie do sklepu.

### 3.6. Endpointy i UI

| Metoda | Ścieżka | Rola | Opis |
|---|---|---|---|
| GET | `/skyshop/links` | auditor+ | produkty z statusem powiązania (filtry: status, search) |
| POST | `/skyshop/links/match` | operator | uruchom auto-matching na mirrorze |
| PATCH | `/skyshop/links/{product_id}` | operator | ręczne powiązanie / wykluczenie |
| POST | `/skyshop/mirror/refresh` | operator | odśwież mirror produktów+kategorii |
| GET | `/skyshop/categories` + `/mappings` | operator | drzewo kategorii + mapowanie |
| GET/PUT | `/products/{id}/content` | operator | dane PIM (opis, zdjęcia, atrybuty, cena) |
| POST | `/skyshop/products/push` | operator | publikacja: `{product_ids: [...], mode: create|update}` |
| POST | `/skyshop/stock/sync` | operator | ręczny delta-push stanów |
| GET | `/skyshop/jobs` | auditor+ | kolejka: statusy, błędy, wyniki |
| POST | `/skyshop/jobs/{id}/retry` / `/cancel` | operator | obsługa dead-letter |

UI: nowa sekcja **„SkyShop”** w sidebarze: *Powiązania produktów* (grid ze
statusami + akcje masowe), *Publikacja/PIM* (edytor treści na karcie produktu),
*Kolejka zadań* (statusy, retry), *Kategorie* (mapowanie). Widget statusu
ostatniej synchronizacji stanów na Dashboardzie.

---

## 4. Migracje (kolejność rewizji Alembic)

1. `integration_accounts` (+ `INTEGRATION_MASTER_KEY` w env, provider konfiguracji z fallbackiem),
2. `warehouse_document_positions` + backfill z `raw` istniejących dokumentów,
3. `stock_reconciliation_lines` (+ ewentualnie `reconciliation_runs`),
4. `skyshop_products`, `skyshop_categories`, `skyshop_product_links`,
   `skyshop_category_mappings`, `product_contents`,
5. `sync_jobs` (+ indeks pickup i częściowy unikalny dedupe),
6. `sync_runs.provider` (rozróżnienie synchronizacji Fakturownia/SkyShop w historii).

Wszystkie zmiany addytywne — zero ryzyka dla istniejących danych.

## 5. Etapy wdrożenia

| Etap | Zakres | Zależności |
|---|---|---|
| 1 | Moduł 1: tabela+szyfrowanie, provider konfiguracji, endpointy, zakładka UI, testy (w tym: sekret nie wycieka) | — |
| 2 | Normalizacja PZ/PW + backfill + mapowanie pozycji dokumentów | 1 (opcjonalnie) |
| 3 | Silnik rozliczeniowy + snapshot + moduł UI + eksporty | 2 |
| 4 | `SkyShopClient` (odczyt) + mirror + matching + UI powiązań | 1 |
| 5 | Kolejka `sync_jobs` + worker + delta-push stanów + kill-switch/dry-run | 3, 4 |
| 6 | PIM: `product_contents`, kategorie, publikacja create/update, zdjęcia | 5 |
| 7 | Testy E2E (mock SkyShop), dokumentacja (ASSUMPTIONS/SYNC update), hardening | 1–6 |

## 6. Ryzyka i decyzje otwarte

* **Szczegóły WebAPI SkyShop są per sklep** (dokumentacja pod `{domena}/api`) —
  sygnatury metod adaptera potwierdzimy po dostępie do konkretnego sklepu;
  architektura (mirror + linki + outbox) jest na to odporna.
* **Brak webhooków** po stronie SkyShop → model pull (mirror refresh cyklicznie).
* **Limit 1 rps**: pełna publikacja np. 5 000 produktów ze zdjęciami to godziny
  pracy kolejki — stąd priorytety (stany > publikacje) i operacje masowe, jeśli
  sklep je udostępnia.
* **Zdjęcia**: jeśli API wymaga URL-i, potrzebny publiczny hosting plików
  (serwowanie z naszego nginx lub S3-kompatybilny bucket) — decyzja na etapie 6.
* **Konflikty SKU/EAN** (wiele dopasowań) → status AMBIGUOUS i ręczne
  rozstrzygnięcie w UI, nigdy automatyczny zapis.
* **Rozliczenie vs ledger**: świadomie dwie równoległe warstwy liczenia
  (operacyjna i dokumentowa) — patrz 2.2; do opisania w ASSUMPTIONS.md.
