#!/usr/bin/env bash
set -euo pipefail

: "${PGDATABASE_URL:?Set PGDATABASE_URL to a PostgreSQL connection URL}"
: "${BACKUP_FILE:?Set BACKUP_FILE to the target .dump path}"

mkdir -p "$(dirname "$BACKUP_FILE")"
pg_dump --format=custom --file="$BACKUP_FILE" --no-owner --no-privileges "$PGDATABASE_URL"
chmod 600 "$BACKUP_FILE"
printf 'backup_written=%s\n' "$BACKUP_FILE"
