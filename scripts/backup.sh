#!/usr/bin/env bash
# Backup bazy PostgreSQL uruchomionej w docker-compose.
# Użycie: ./scripts/backup.sh [katalog_docelowy]
set -euo pipefail

TARGET_DIR="${1:-./backups}"
mkdir -p "$TARGET_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
FILE="$TARGET_DIR/erp_wms_$STAMP.dump"

docker compose exec -T db pg_dump \
  -U "${POSTGRES_USER:-erp}" -d "${POSTGRES_DB:-erp_wms}" \
  --format=custom > "$FILE"

echo "Backup zapisany: $FILE"
