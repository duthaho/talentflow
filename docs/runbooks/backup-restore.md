# PostgreSQL backup and restore runbook

## Recovery objectives

- **Backup frequency:** daily full logical backups, retained for 35 days; retain monthly backups for 12 months according to the organization retention policy.
- **RPO:** 24 hours with daily logical backups. A production system requiring a smaller RPO must add managed point-in-time recovery before changing this claim.
- **RTO target:** restore and validate service within 4 hours for the current expected data volume.
- **Security:** encrypt backups at rest with the organization-managed KMS key; transfer only over TLS; restrict read/restore access to the incident and database-operations roles.

## Create a backup

The scripts intentionally require the PostgreSQL connection URL and destination as environment variables, avoiding command-line credentials:

```bash
export PGDATABASE_URL='postgresql://backup-user:password@db.example/talentflow'
export BACKUP_FILE="/secure/backups/talentflow-$(date -u +%F).dump"
./scripts/backup-postgres.sh
```

Store the resulting custom-format dump outside the application host. Confirm the backup object size, checksum in the backup system, and encryption status. Do not commit or log the connection URL.

## Restore drill

Perform this at least quarterly in an isolated PostgreSQL instance, never over the production database.

1. Record the source backup identifier, UTC time, operator, target environment, and start time.
2. Provision an empty isolated PostgreSQL database; block application and worker access to it.
3. Restore with:

   ```bash
   export PGDATABASE_URL='postgresql://restore-user:password@restore-db.example/talentflow'
   export BACKUP_FILE=/secure/backups/talentflow-YYYY-MM-DD.dump
   ./scripts/restore-postgres.sh
   ```

4. Run `alembic current` against the restored database and record the revision.
5. Start the candidate API image against the isolated database. Verify `/health/ready`, tenant-scoped read access, and `/metrics` without exposing restored data externally.
6. Compare critical table row counts and the latest audit-event timestamp with the backup manifest. Verify notification workers are disabled during the drill to prevent email from restored data.
7. Record completion time, results, defects, and any RPO/RTO variance. Destroy the isolated restore environment and securely remove temporary dump copies.

## Production recovery decision

Before a production restore, declare an incident, stop API writes and worker schedules, take a final backup if possible, identify the target restore point, and obtain incident-lead approval. After restore, validate schema revision, data integrity, OIDC configuration, and worker state before reopening writes. Notify stakeholders when the actual RPO/RTO is known.
