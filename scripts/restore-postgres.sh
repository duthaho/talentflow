#!/usr/bin/env bash
set -euo pipefail

: "${PGDATABASE_URL:?Set PGDATABASE_URL to the target PostgreSQL connection URL}"
: "${BACKUP_FILE:?Set BACKUP_FILE to the source .dump path}"

if [[ ! -f "$BACKUP_FILE" ]]; then
  printf 'backup file does not exist: %s\n' "$BACKUP_FILE" >&2
  exit 1
fi

pg_restore --clean --if-exists --no-owner --no-privileges --dbname="$PGDATABASE_URL" "$BACKUP_FILE"
printf 'restore_completed=%s\n' "$BACKUP_FILE"
