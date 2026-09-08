#!/usr/bin/env bash
# Odtworzenie bazy PostgreSQL z backupu (format custom pg_dump).
# Użycie: ./scripts/restore.sh backups/erp_wms_20250101_120000.dump
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Użycie: $0 <plik.dump>" >&2
  exit 1
fi

FILE="$1"
echo "UWAGA: baza ${POSTGRES_DB:-erp_wms} zostanie nadpisana danymi z $FILE"
read -r -p "Kontynuować? [tak/NIE] " CONFIRM
if [ "$CONFIRM" != "tak" ]; then
  echo "Przerwano."
  exit 1
fi

docker compose exec -T db pg_restore \
  -U "${POSTGRES_USER:-erp}" -d "${POSTGRES_DB:-erp_wms}" \
  --clean --if-exists --no-owner < "$FILE"

echo "Baza odtworzona z $FILE"
