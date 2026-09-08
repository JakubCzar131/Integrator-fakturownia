# Synchronizacja z Fakturownią

## Zasady ogólne

* Wyłącznie żądania **GET** (guard opisany w README i ARCHITECTURE).
* Token API dołączany jako parametr `api_token` (wymóg Fakturowni); nigdy nie
  jest logowany — URL-e przechodzą przez maskowanie sekretów.
* Paginacja `page` + `per_page` (domyślnie 100, konfigurowalne).
* Rate limiting: minimalny odstęp między żądaniami
  (`FAKTUROWNIA_RATE_LIMIT_RPS`).
* Retry z backoffem wykładniczym (2^n s, max 60 s) dla 429/5xx i błędów
  sieciowych; honorowany nagłówek `Retry-After`. Kody 4xx inne niż 429 są
  błędem trwałym (bez retry).

## Pobierane zasoby (endpointy Fakturowni)

| Zasób | Endpoint | Tryb |
|---|---|---|
| Faktury + pozycje | `GET /invoices.json?period=all&include_positions=true` | pełna: `period=all`; przyrostowa: `period=more&date_from=…&date_to=…` |
| Pojedyncza faktura | `GET /invoices/{id}.json` | dostępny w kliencie (uzupełnianie danych) |
| Produkty | `GET /products.json` | zawsze wszystkie strony |
| Stany per magazyn | `GET /products.json?warehouse_id={id}` | dla każdego magazynu z Fakturowni |
| Magazyny | `GET /warehouses.json` | całość |
| Dokumenty magazynowe | `GET /warehouse_documents.json` | całość |
| Akcje magazynowe | `GET /warehouse_actions.json` | całość |
| Klienci | `GET /clients.json` | całość |
| Kategorie | `GET /categories.json` | całość |
| Działy | `GET /departments.json` | całość |
| Płatności | `GET /banking/payments.json?include=invoices` | całość (odczyt do analityki) |
| Cenniki | `GET /price_lists.json` | całość |

## Idempotencja i wykrywanie zmian

* Każdy rekord jest upsertowany po `fakturownia_id`.
* SHA-256 kanonicznego JSON-a payloadu przechowywany w `payload_hash`;
  niezmieniony hash → rekord liczony jako `unchanged`, bez zapisu snapshotu.
* Zmieniony/nowy rekord → wpis w `source_snapshots` (append-only, pełny JSON)
  + aktualizacja tabeli mirror. Snapshoty tworzą pełną historię odpowiedzi
  źródła w czasie.
* Pozycje faktury są synchronizowane razem z fakturą; pozycje usunięte
  z payloadu są usuwane z mirroru (historia zostaje w snapshotach).

## Wykrywanie usunięć i anulowań

* **Pełna synchronizacja** zbiera zbiór `fakturownia_id` zwróconych przez API;
  rekordy lokalne spoza zbioru dostają flagę `is_deleted_upstream = true`
  (fizycznie nic nie jest kasowane). Dokumenty z tą flagą nie uczestniczą
  w rozliczaniu magazynu.
* Anulowanie wykrywane z payloadu (`cancelled` / `status = cancelled`).

## Synchronizacja przyrostowa

* Watermark: `app_settings.last_successful_sync_at` (zapis po każdej w pełni
  udanej synchronizacji).
* Faktury pobierane od `watermark − 7 dni` (zakładka niweluje edycje
  wsteczne) do dziś; pozostałe zasoby odświeżane w całości z tanim skip po
  hashu.
* **Ograniczenie:** faktura edytowana z datą wystawienia starszą niż okno nie
  zostanie wykryta przyrostowo — zalecana okresowa pełna synchronizacja
  (np. raz dziennie w nocy).

## Historia i monitoring

* `sync_runs`: typ (FULL/INCREMENTAL), status (RUNNING/SUCCESS/PARTIAL/FAILED),
  czas trwania, liczniki fetched/created/updated/unchanged, błędy per zasób,
  statystyki per zasób (JSON).
* Błąd jednego zasobu nie przerywa pozostałych kroków — uruchomienie kończy
  się jako `PARTIAL` z listą błędów w panelu Synchronizacja.
* Ręczne uruchomienie: przyciski w panelu / `POST /sync/full`,
  `POST /sync/incremental` (rola operator/admin). Mutex gwarantuje jedną
  synchronizację naraz (409 przy próbie równoległej).
* Harmonogram: APScheduler w procesie backendu
  (`SYNC_SCHEDULE_ENABLED=true`, `SYNC_INTERVAL_MINUTES=…`), używa tej samej
  blokady co uruchomienia ręczne.
