# Backup and restore (Docker Compose stack)

This runbook backs up and restores the local Compose stack: the PostgreSQL database and the attachment files. It replaces the cloud-oriented version (KMS, managed PITR), which belonged to the archived AWS track.

The data here is local demo data. Still treat a dump as sensitive: it contains candidate PII from the seed or from anything you entered. Never commit a dump. The commands write to `data/backups/`, which `.gitignore` already excludes (`data/`).

## What holds state

| Data | Where today | Where after stage 2 |
| --- | --- | --- |
| Database | `postgres` service, volume `<project>_postgres_data` | same (image becomes `pgvector/pgvector`, DUTH-50) |
| Attachment bytes | volume `<project>_attachment_data`, mounted at `/app/data/attachments` in `api` and `retention-worker` | SeaweedFS bucket (DUTH-49); this runbook gains an object-store section then |
| Redis | rate-limit counters only, no persistence configured | same — nothing to back up |

`<project>` is the Compose project name: the checkout directory name (usually `talentflow`) unless `COMPOSE_PROJECT_NAME` is set. List the volumes with `docker volume ls --filter name=_data`.

Run all commands from the repository root with the stack up (`docker compose up -d`).

## Back up

```bash
mkdir -p data/backups
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
PROJECT=${COMPOSE_PROJECT_NAME:-talentflow}

# Database: custom-format dump, streamed out of the container
docker compose exec -T postgres \
  pg_dump -U talentflow -d talentflow --format=custom --no-owner --no-privileges \
  > "data/backups/talentflow-$STAMP.dump"

# Attachments: tar the volume read-only
docker run --rm \
  -v "${PROJECT}_attachment_data:/data:ro" \
  -v "$PWD/data/backups:/backup" \
  postgres:17-alpine tar -czf "/backup/attachments-$STAMP.tgz" -C /data .

chmod 600 data/backups/*
```

Take both in the same quiet moment (no requests, workers idle) so database rows and files match. If you have `pg_dump` 17 on the host, `scripts/backup-postgres.sh` does the same with `PGDATABASE_URL=postgresql://talentflow:talentflow@localhost:5432/talentflow` (local dev credentials only).

## Restore drill (non-destructive)

Restore into a scratch database next to the live one and check it. Do this after any change to migrations or the backup commands.

```bash
DUMP=data/backups/talentflow-<STAMP>.dump

docker compose exec -T postgres createdb -U talentflow talentflow_restore
docker compose exec -T postgres \
  pg_restore -U talentflow -d talentflow_restore --no-owner --no-privileges < "$DUMP"

# Expect the current Alembic head and plausible row counts
docker compose exec -T postgres psql -U talentflow -d talentflow_restore -tAc \
  "select version_num from alembic_version"
docker compose exec -T postgres psql -U talentflow -d talentflow_restore -tAc \
  "select count(*) from candidate_cases"

docker compose exec -T postgres dropdb -U talentflow talentflow_restore
```

Compare `version_num` with `uv run alembic heads`. Record the date, dump name and result if you keep a drill log.

## Full restore (replaces current data)

1. Stop everything that writes, so workers cannot send email from restored data:

   ```bash
   docker compose stop api notification-worker retention-worker
   ```

2. Restore the database over the live one:

   ```bash
   docker compose exec -T postgres \
     pg_restore -U talentflow -d talentflow --clean --if-exists --no-owner --no-privileges \
     < data/backups/talentflow-<STAMP>.dump
   ```

3. Restore the attachments into an emptied volume:

   ```bash
   PROJECT=${COMPOSE_PROJECT_NAME:-talentflow}
   docker run --rm -v "${PROJECT}_attachment_data:/data" postgres:17-alpine \
     sh -c 'find /data -mindepth 1 -delete'
   docker run --rm \
     -v "${PROJECT}_attachment_data:/data" \
     -v "$PWD/data/backups:/backup:ro" \
     postgres:17-alpine tar -xzf /backup/attachments-<STAMP>.tgz -C /data
   ```

4. Start the stack. `migrate` runs `alembic upgrade head` first, so an older dump is brought forward:

   ```bash
   docker compose up -d
   curl -fsS http://127.0.0.1:8000/health/ready
   ```

## Start from scratch instead

When you do not need the data, `docker compose down -v` deletes all volumes and `docker compose up -d` recreates an empty, migrated database.

## Verification record

Verified on 2026-11-24 against `docker-compose.yml` at `db1f7bc` (Docker 29.4, Compose v5.1, `postgres:17-alpine`): dump, scratch restore (Alembic revision and row count matched), destructive `--clean` restore, and attachment volume tar round-trip.
