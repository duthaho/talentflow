# Production infrastructure readiness roadmap

## Status and boundary

TalentFlow has application-level readiness controls: OIDC/JWT validation, Alembic migrations, Redis-backed rate limiting, Prometheus metrics, JSON logs with correlation IDs, OpenTelemetry FastAPI instrumentation, CI/security workflows, private attachment storage, retention purge, and recovery runbooks.

These are **code and CI evidence**, not proof of a live production deployment. The following plan turns those controls into operated infrastructure. It intentionally does not introduce microservices.

## Target operating model

- **Runtime:** immutable API and bounded-worker images, deployed to a managed container platform or Kubernetes; PostgreSQL, Redis, and private object storage are managed services.
- **Telemetry:** OpenTelemetry is the vendor-neutral application contract. Export traces and structured logs through an OpenTelemetry Collector. Use one initial backend: Datadog *or* Grafana Cloud/Prometheus + Loki + Tempo. Do not run Datadog and a self-hosted ELK stack in the first production release.
- **Error tracking:** Sentry SDK for unhandled exceptions and sampled performance transactions; scrub PII, authorization headers, cookies, request bodies, candidate emails, attachment filenames, and feed tokens before export.
- **Alerting:** PagerDuty/Opsgenie (paging) plus Slack/Teams (non-page notifications). Alertmanager or the chosen observability provider routes alerts; the application never sends operational pages directly.

## Delivery order

### Phase 0 — Production foundations and ownership

**Outcome:** one accountable production environment and measurable service objectives.

1. Select cloud/platform, regions, DNS, container registry, secret manager, managed PostgreSQL with PITR, managed Redis, and private object storage.
2. Define owners, escalation schedule, severity policy, maintenance windows, SLOs, error budgets, RPO/RTO, and a data-classification policy.
3. Provision separate dev, staging, and production accounts/projects. Production has no shared credentials or databases with lower environments.
4. Manage all infrastructure with Terraform/OpenTofu; remote state is encrypted, locked, and access-controlled.
5. Enforce least-privilege workload identities. No long-lived cloud keys or observability DSNs in GitHub repository secrets when OIDC federation is available.

**Initial SLOs:** API availability 99.9%; 99% read latency <300 ms; 99% write latency <700 ms; worker backlog age <10 minutes; error budget measured monthly. Calibrate after real traffic.

### Phase 1 — Error tracking, logs, metrics, and distributed tracing

**Outcome:** every user-impacting failure can be correlated from alert to trace, log, deployment, and runbook.

1. Add Sentry FastAPI/SQLAlchemy integration behind `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_RELEASE`, and bounded trace/error sampling settings. Production startup validates complete Sentry configuration only when enabled.
2. Implement `before_send` and trace-sampling hooks that redact PII/secrets; default to no request bodies, no headers, and no attachment metadata. Test redaction explicitly.
3. Add OpenTelemetry exporters (OTLP) and resource attributes: service name/version, environment, deployment SHA, region, and worker role. Preserve correlation IDs as span/log attributes, never metric labels.
4. Deploy an OpenTelemetry Collector as the only exporter target from workloads. Collector handles batching, retries, filtering, tail sampling, and fan-out to Sentry/Datadog or Grafana backends.
5. Standardize structured logs to stdout JSON. Ship through platform agent/Collector; retain 30 days hot and archive according to compliance policy. Implement log-based alerts only for bounded event classes.
6. Add operational dashboards: RED (rate/errors/duration), PostgreSQL/Redis health, outbox backlog and age, notification delivery outcomes, retention worker result, rate-limit rejects, attachment scanner availability, and audit-write failures.

### Phase 2 — Alerting and incident response

**Outcome:** actionable alerts reach the correct team with clear ownership and no PII.

1. Define alert tiers: page only for user-impacting SLO burn, sustained 5xx, readiness failure across replicas, database/Redis failure, queue/backlog breach, and backup/restore failure. Ticket/chat notifications cover vulnerability findings, elevated 4xx, worker zero-progress, capacity trends, and certificate expiry.
2. Add alerts with multi-window burn-rate logic; avoid single noisy thresholds. Every alert has severity, service, environment, dashboard link, trace/log query, runbook URL, and deduplication key.
3. Create runbooks for API outage, dependency outage, queue/delivery backlog, retention failure, incident communications, security incident, and rollback. Exercise tabletop scenarios before launch.
4. Send deploy, rollback, failed pipeline, critical vulnerability, and production alert notifications via the delivery platform—not application business-notification code.

### Phase 3 — CI/CD and progressive deployment

**Outcome:** each production change is traceable, policy-gated, reversible, and promoted without rebuild.

1. Keep existing lint/test/migration/security jobs. Add SBOM generation, dependency/license policy, image signing (Cosign), provenance attestation, and registry digest verification.
2. Build once on main; tag image with commit SHA and publish immutable digest. Deploy the same digest to staging then production.
3. Authenticate GitHub Actions to cloud/registry using GitHub OIDC federation. Protect production environment with required reviewers, change record link, concurrency lock, and least-privilege deploy role.
4. Add staging deploy smoke checks: migration, readiness, authenticated JWT request, Redis rate-limit path, attachment scanner readiness, worker dry-run/bounded cycle, and rollback compatibility.
5. Use canary or blue/green rollout. Automatically halt/rollback only on pre-defined health/SLO regressions; database migrations follow expand/contract compatibility rules.
6. Emit deployment markers to Sentry/telemetry and record image digest, migration revision, operator, time, and change reference.

### Phase 4 — Performance and load testing

**Outcome:** capacity is measured against production-like dependencies before launch.

1. Define realistic load profiles: candidate search/read-heavy, workflow writes with optimistic conflicts, interview scheduling, attachment upload/download, calendar-feed polling, reporting queries, and worker backlog recovery.
2. Implement k6 tests with synthetic tenants and non-PII fixtures. Keep scripts in `tests/load/`; never target production without an approved window and stop conditions.
3. Run baseline tests in staging, then stress/soak tests against isolated capacity. Record p50/p95/p99, saturation, database locks, Redis latency, connection pools, GC/CPU/memory, storage throughput, and error rate.
4. Set explicit abort thresholds and capacity targets. Tune indexes/query plans, worker batch sizes, connection limits, and replica counts from evidence; do not scale blindly.
5. Repeat performance tests for every material query, schema, attachment, or infrastructure change.

### Phase 5 — Production validation and continuous operations

**Outcome:** launch is backed by operational evidence, not configuration claims.

1. Run a production-readiness review: threat model, IAM review, secret rotation, OIDC test, verified SendGrid test, malware scanner test, backup restore drill, alert delivery test, and rollback drill.
2. Launch with a limited tenant cohort; observe SLOs, alert quality, and cost for at least one error-budget window.
3. Schedule quarterly restore drills, access reviews, alert/runbook reviews, dependency upgrades, load regression tests, and incident simulations.

## Explicit non-goals for first production release

- Self-hosted ELK plus Datadog simultaneously.
- Provider-specific Google/Microsoft calendar OAuth synchronization.
- Automatic database schema downgrades during deploy.
- Unbounded background loops or in-application paging.
- Production load testing against customer data.

## Acceptance evidence

A phase is complete only with version-controlled configuration, passing automated tests, successful staging evidence, named owner, dashboard/alert links, and a dated drill or verification record. Secrets, DSNs, customer data, access tokens, and raw trace/log payloads are never committed.
