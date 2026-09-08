# WMS Kontrola — lokalny system ERP/WMS do kontroli sprzedaży z Fakturowni

Niezależny, lokalny panel kontrolny ERP/WMS połączony z Fakturownią **wyłącznie
w trybie odczytu (GET)**. System pobiera faktury, pozycje, produkty, klientów,
magazyny, dokumenty i akcje magazynowe, buduje **własny lokalny magazyn**
(stany początkowe, ledger, korekty) i **waliduje ilości sprzedane na
fakturach** względem lokalnych stanów magazynowych.

> **Zasada nadrzędna:** Fakturownia jest tylko źródłem danych. System nigdy nie
> tworzy, nie edytuje i nie usuwa niczego w Fakturowni. Klient API technicznie
> blokuje każde żądanie inne niż GET (szczegóły niżej).

## Stos technologiczny

| Warstwa | Technologia |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2 |
| Baza danych | PostgreSQL 16 |
| Zadania cykliczne | APScheduler (synchronizacja przyrostowa w tle) |
| Frontend | React 19 + TypeScript + Vite, autorski design system ERP |
| Testy | pytest (63 testy jednostkowe i integracyjne) |
| Infrastruktura | Docker, docker-compose, nginx |

## Szybki start (Docker Compose)

```bash
# 1. Konfiguracja środowiska
cp .env.example .env
#    Uzupełnij co najmniej:
#    - POSTGRES_PASSWORD, SECRET_KEY, ADMIN_EMAIL, ADMIN_PASSWORD
#    - FAKTUROWNIA_DOMAIN, FAKTUROWNIA_API_TOKEN

# 2. Uruchomienie (migracje bazy wykonują się automatycznie)
docker compose up -d --build

# 3. Panel ERP:      http://localhost:8080
#    API + Swagger:  http://localhost:8000/api/docs (przez 127.0.0.1)
```

Zaloguj się kontem administratora z `.env` (`ADMIN_EMAIL` / `ADMIN_PASSWORD`),
następnie na Dashboardzie kliknij **Pełna synchronizacja**, a po jej
zakończeniu **Uruchom walidację**.

## Konfiguracja `.env`

Wszystkie sekrety żyją wyłącznie w zmiennych środowiskowych — patrz
`.env.example` z opisem każdej zmiennej. Najważniejsze:

| Zmienna | Opis |
|---|---|
| `FAKTUROWNIA_DOMAIN` | subdomena konta: `https://{DOMENA}.fakturownia.pl` |
| `FAKTUROWNIA_API_TOKEN` | token API (Ustawienia → Integracje). **Nie trafia do repo, bazy ani logów** |
| `DATABASE_URL` | połączenie z PostgreSQL |
| `SECRET_KEY` | klucz podpisywania JWT (`openssl rand -hex 32`) |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | konto administratora tworzone przy pierwszym starcie |
| `SYNC_SCHEDULE_ENABLED`, `SYNC_INTERVAL_MINUTES` | harmonogram automatycznej synchronizacji przyrostowej |

## Read-only guard dla Fakturowni

Klient API (`backend/app/services/fakturownia_client.py`) ma **trzy niezależne
warstwy ochrony**:

1. `request()` dopuszcza wyłącznie metodę `GET` — każda inna podnosi
   `FakturowniaReadOnlyViolation` **zanim powstanie ruch sieciowy**;
2. metody `post/put/patch/delete` istnieją tylko jako „zatrute” metody, które
   zawsze rzucają wyjątek;
3. hook transportowy `httpx` sprawdza **każde** wychodzące żądanie — nawet kod
   omijający wrapper i używający wewnętrznego klienta HTTP zostanie zablokowany.

Każda zablokowana próba zapisuje wpis `READONLY_VIOLATION_BLOCKED` w lokalnym
audycie (`audit_log`). Testy `app/tests/test_fakturownia_client_readonly.py`
potwierdzają odrzucenie POST/PUT/PATCH/DELETE na wszystkich warstwach oraz
maskowanie tokenu w komunikatach błędów i logach.

## Synchronizacja

* **Pełna** (`POST /api/v1/sync/full` albo przycisk w panelu) — pobiera
  wszystkie zasoby: działy, kategorie, magazyny, produkty, stany per magazyn,
  klientów, faktury z pozycjami (`period=all&include_positions=true`),
  dokumenty magazynowe, akcje magazynowe, płatności, cenniki.
* **Przyrostowa** (`POST /api/v1/sync/incremental`) — faktury z okna czasowego
  od ostatniej udanej synchronizacji (z 7-dniową zakładką), pozostałe zasoby
  odświeżane z pominięciem rekordów o niezmienionym hashu.
* Import jest **idempotentny**: upsert po `fakturownia_id` + porównanie
  SHA-256 payloadu; ponowne uruchomienie niczego nie duplikuje.
* Surowe odpowiedzi JSON trafiają do `source_snapshots` (append-only),
  a historia uruchomień do `sync_runs` (widoczna w module Synchronizacja).
* Retry z backoffem wykładniczym (429/5xx, honoruje `Retry-After`),
  limitowanie zapytań (`FAKTUROWNIA_RATE_LIMIT_RPS`), paginacja `page`/`per_page`.
* Rekordy, których API już nie zwraca, są oznaczane `is_deleted_upstream`
  (nigdy nie są fizycznie usuwane). Szczegóły: [docs/SYNC.md](docs/SYNC.md).

## Lokalny magazyn

* `opening_balances` — ręczne stany początkowe (produkt × magazyn, na dzień),
* `local_stock_adjustments` — ręczne korekty (wymagany opis; odwracanie przez
  **storno**, nigdy przez kasowanie historii),
* `local_stock_ledger` — **pochodna** projekcja wszystkich ruchów
  (`OPENING_BALANCE`, `SALE`, `SALE_CORRECTION`, `MANUAL_ADJUSTMENT`,
  `IMPORTED_WAREHOUSE_ACTION`) z saldem przed/po każdej operacji,
* `local_stock_balances` — bieżące salda per produkt × magazyn.

Ledger można w każdej chwili **przebudować od zera**
(`POST /api/v1/stock/recalculate` lub przycisk „Przelicz stany od nowa”).
Sprzedaż z faktur pomniejsza stan, korekty go przywracają, usługi/produkty
ignorowane nie dotykają magazynu, zestawy rozliczają się przez lokalnie
zdefiniowany skład. Szczegóły: [docs/STOCK.md](docs/STOCK.md).

## Mapowania produktów

Pozycje faktur są rozpoznawane w kolejności: `product_id` → zatwierdzone
mapowanie (sygnatura nazwa/kod/EAN/jm.) → alias użytkownika → dokładny kod →
EAN → nazwa. Dopasowania niepewne mają status `PROPOSED` i czekają na
zatwierdzenie w module **Mapowania produktów**; konflikty (wiele produktów
pasuje) są raportowane jako `MAPPING_CONFLICT`. Po zatwierdzeniu mapowania
system od razu przelicza pozycje, a walidację można uruchomić jednym
przyciskiem.

## Walidacje

Silnik walidacji sprawdza 20 reguł (rozpoznanie produktu, ilości, jednostki,
pokrycie magazynowe, stany ujemne, duplikaty, anulacje, korekty, brakujące
stany początkowe, rozbieżności ze stanami Fakturowni itd.) i tworzy problemy
z pełnym kontekstem: faktura, pozycja, produkt, magazyn, stan przed/po, opis
techniczny i biznesowy, rekomendowana akcja, komentarze, historia. Problemy
mają stabilny klucz deduplikacji — ponowna walidacja aktualizuje istniejące
wpisy, zamyka nieaktualne (auto-RESOLVED) i szanuje decyzje operatora
(IGNORED). Szczegóły: [docs/VALIDATION.md](docs/VALIDATION.md).

## Audyt

Każda lokalna operacja (logowania, zmiany mapowań, korekty magazynu, zmiany
statusów problemów, zmiany ustawień, eksporty, próby zapisu do Fakturowni)
trafia do `audit_log` z użytkownikiem, datą, IP oraz starą/nową wartością.
Moduł **Audyt** pozwala filtrować i przeglądać pełną historię.

## Testy

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest app/tests -v
```

Testy pokrywają m.in.: blokadę wszystkich metod zapisu do Fakturowni,
idempotencję synchronizacji, snapshoty JSON, logikę ledgera (sprzedaż,
korekty, storno, zestawy, przebudowa), 20 reguł walidacji, RBAC (admin /
operator / auditor), eksporty CSV/XLSX/PDF i maskowanie sekretów.

## Backup i restore PostgreSQL

```bash
# backup (format custom pg_dump, katalog ./backups)
./scripts/backup.sh

# restore (nadpisuje bazę!)
./scripts/restore.sh backups/erp_wms_20250101_120000.dump
```

Bez skryptów:

```bash
docker compose exec -T db pg_dump -U erp -d erp_wms --format=custom > backup.dump
docker compose exec -T db pg_restore -U erp -d erp_wms --clean --if-exists < backup.dump
```

## Wdrożenie produkcyjne

Rekomendowane środowisko: serwer w sieci lokalnej firmy, Docker Compose,
frontend wystawiony na port 8080 (lub za firmowym reverse proxy z TLS),
backend i PostgreSQL dostępne tylko z localhost. Checklist, aktualizacje
i hardening: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Development bez Dockera

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example ../.env   # i uzupełnij
export DATABASE_URL=postgresql+psycopg2://erp:erp@localhost:5432/erp_wms
alembic upgrade head
uvicorn app.main:app --reload

# Frontend (proxy /api -> localhost:8000)
cd frontend
npm install
npm run dev
```

## Dokumentacja

| Plik | Zawartość |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | architektura, moduły, przepływy danych |
| [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md) | **wszystkie założenia biznesowe** (typy dokumentów, korekty, usługi, braki danych) |
| [docs/API.md](docs/API.md) | lokalne API REST |
| [docs/SYNC.md](docs/SYNC.md) | synchronizacja pełna/przyrostowa, snapshoty, wykrywanie zmian |
| [docs/VALIDATION.md](docs/VALIDATION.md) | reguły walidacji, statusy, cykl życia problemu |
| [docs/STOCK.md](docs/STOCK.md) | lokalny magazyn, ledger, przeliczanie |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | wdrożenie produkcyjne, backup, aktualizacje |

## Struktura projektu

```
backend/
  app/
    main.py, config.py, logging_config.py, bootstrap.py
    api/routes/        # endpointy REST (auth, sync, invoices, stock, validation…)
    audit/             # audyt lokalny
    database/          # engine, sesje, Base
    models/            # SQLAlchemy: 30+ tabel
    repositories/      # paginacja/sortowanie
    schemas/           # Pydantic
    security/          # JWT, bcrypt, RBAC
    services/          # fakturownia_client, sync, mapping, stock, validation, report
    tests/             # pytest
  alembic/             # migracje
frontend/
  src/
    components/erp/    # design system: Sidebar, Topbar, StatusBadge, FilterBar…
    components/datagrid/  # DataGrid (sortowanie, kolumny, paginacja, preferencje)
    modules/           # dashboard, invoices, products, stock, validation, reports…
    lib/               # api.ts, types.ts, auth, formatowanie
docs/                  # dokumentacja
scripts/               # backup.sh, restore.sh
docker-compose.yml
.env.example
```
