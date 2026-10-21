# Deployment runbook

## Scope and release contract

TalentFlow is deployed as an API process plus a bounded notification worker, backed by PostgreSQL. The deployment artifact is an immutable image tagged with both the Git commit SHA and an immutable registry digest. Promote the same digest between environments; do not rebuild an image during promotion.

Required runtime configuration:

- `APP_ENV=production`
- `AUTH_MODE=oidc_jwt`
- `DATABASE_URL` — PostgreSQL URL delivered from the platform secret manager
- `CORS_ALLOWED_ORIGINS` — explicit comma-separated HTTPS origins
- `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL`
- `WORKER_LEASE_SECONDS`, `WORKER_MAX_ATTEMPTS` — optional bounded worker controls
- `SENDGRID_API_KEY` and `NOTIFICATION_FROM_EMAIL` — required only for the email-delivery worker and supplied together

Never put production values in Compose files, image layers, GitHub Actions logs, or `.env` files committed to the repository.

## Release procedure

1. Confirm the candidate commit passed the `CI` and `Security` workflows. Review migration changes before approval.
2. Build once and publish as `registry.example/talentflow:<git-sha>`; record its image digest in the release record.
3. Start a one-shot migration job using that exact digest:

   ```bash
   alembic upgrade head
   ```

   The job must complete before an API rollout. It is safe to rerun an Alembic upgrade, but do not run destructive migrations without a tested rollback plan and a verified backup.
4. Deploy API instances with readiness checks on `/health/ready` and liveness checks on `/health/live`. Do not route traffic until readiness succeeds.
5. Schedule the bounded notification and retention worker cycles using the same exact image digest:

   ```bash
   python -m app.modules.notifications.application.run_email_worker
   python -m app.modules.retention.application.run_retention_worker
   ```

   The notification cycle materializes outbox work and attempts delivery with durable leases. The retention cycle processes a configured bounded tenant set and may delete eligible private attachment bytes before anonymizing candidate PII. Record each schedule and its execution outcome in platform telemetry.
6. Verify `/metrics`, inspect structured logs by `correlation_id`, and check migration revision with `alembic current`.

## Rollback

- **Application-only rollback:** deploy the prior known-good image digest after confirming it remains compatible with the current schema.
- **Schema rollback:** only run `alembic downgrade` from a reviewed, reversible migration and only after a fresh backup. Prefer expand/contract migrations so an application rollback does not require immediate schema rollback.
- **Delivery incident:** stop the worker schedule, retain outbox/delivery rows, diagnose, then restart. Expired leases are reclaimed automatically; do not manually mark rows delivered without evidence from the provider.

## Local Compose note

`docker-compose.yml` is development-only and uses non-secret local PostgreSQL credentials. It runs a one-shot migration service before the API. Production platforms should translate the same contract into managed secrets, a migration job, API workload, and worker schedule.
