# Wdrożenie produkcyjne

## Środowisko docelowe

System jest projektowany do pracy w **sieci lokalnej firmy** (LAN/VPN):

* frontend (nginx) — port `8080` na wszystkich interfejsach,
* backend (uvicorn) i PostgreSQL — związane z `127.0.0.1` (dostęp tylko
  z hosta i sieci docker); do backendu z zewnątrz prowadzi wyłącznie proxy
  `/api` w nginx.

## Checklist przed startem

1. `cp .env.example .env` i ustaw:
   * silne `POSTGRES_PASSWORD`, `SECRET_KEY` (`openssl rand -hex 32`),
     `ADMIN_PASSWORD`;
   * `FAKTUROWNIA_DOMAIN` i `FAKTUROWNIA_API_TOKEN`;
   * `ENVIRONMENT=production`, `DEBUG=false`.
2. `docker compose up -d --build` — entrypoint backendu wykonuje
   `alembic upgrade head` przed startem serwera.
3. Zaloguj się kontem administratora, utwórz konta operatorów/audytorów
   (moduł Użytkownicy i role) i **zmień hasło admina**, jeśli w `.env` było
   tymczasowe.
4. Uruchom pełną synchronizację i walidację; skonfiguruj harmonogram
   (`SYNC_SCHEDULE_ENABLED=true`).

## TLS / reverse proxy (opcjonalnie)

Jeżeli panel ma być dostępny po HTTPS, postaw przed portem 8080 firmowy
reverse proxy (nginx/traefik/caddy) z certyfikatem i przekazuj nagłówek
`X-Forwarded-For` (backend używa go do zapisu IP w audycie).

## Backup

* `./scripts/backup.sh [katalog]` — `pg_dump --format=custom`.
* Zalecany cron na hoście, np. codziennie o 02:00:

```cron
0 2 * * * cd /opt/erp-wms && ./scripts/backup.sh /opt/erp-wms/backups >> /var/log/erp-backup.log 2>&1
```

* Przechowuj kopie poza hostem (NAS/S3). Odtwarzanie:
  `./scripts/restore.sh backups/plik.dump` (interaktywne potwierdzenie).

## Aktualizacja wersji

```bash
git pull
docker compose build
docker compose up -d       # migracje wykonają się automatycznie
```

Migracje Alembic są addytywne; przed większymi aktualizacjami wykonaj backup.

## Monitoring i diagnostyka

* `GET /api/v1/health` — healthcheck (używany też przez Dockera).
* `docker compose logs -f backend` — logi z maskowaniem sekretów.
* Moduł **Synchronizacja** — błędy API Fakturowni per uruchomienie.
* Moduł **Audyt** — wszystkie operacje lokalne oraz ewentualne wpisy
  `READONLY_VIOLATION_BLOCKED` (nie powinny występować w normalnej pracy).

## Utrzymanie danych

* `source_snapshots` rośnie wraz ze zmianami danych źródłowych (snapshot
  tylko przy zmianie hasha). Przy bardzo dużych wolumenach można archiwizować
  stare snapshoty (np. starsze niż rok) własnym skryptem SQL — tabele
  aplikacyjne są od nich niezależne.
* `local_stock_ledger` jest w pełni odtwarzalny (`POST /stock/recalculate`),
  nie wymaga archiwizacji.
