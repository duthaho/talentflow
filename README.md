# TalentFlow

TalentFlow is a **multi-tenant HR candidate workflow and case-management platform** (an applicant tracking system). It takes a candidate from application through interviews and a staged offer approval, with tenant isolation, role-based access, audit, optimistic concurrency and reliable asynchronous notifications.

It is a **learning showcase**: one complete, runnable application that shows how an enterprise system is designed, built, operated and evolved. Every pattern is backed by code, tests and a short doc or ADR you can read side by side. It is written for engineers who want to see enterprise patterns in a codebase small enough to read in an afternoon, not in slides.

> **Architecture:** modular monolith with Clean/Hexagonal boundaries per bounded context, CQRS-lite, transactional outbox, idempotent background delivery. Python 3.13, FastAPI, SQLAlchemy 2, PostgreSQL, Redis.

## Where it is going

The v2 plan (DUTH-43) makes TalentFlow fully runnable on a laptop: `docker compose up` brings up the API, workers, a Next.js web app and an all-open-source supporting stack — Keycloak, PostgreSQL + pgvector, Redis, RabbitMQ, OpenSearch, SeaweedFS (S3), ClamAV, Mailpit, OpenBao, flagd, OpenTelemetry + Grafana, GlitchTip and Ollama. There is no cloud deployment.

- [Roadmap](docs/roadmap.md) — nine stages, their issues and the patterns each one teaches
- [Architecture](docs/architecture.md) — current and target, with C4 diagrams
- [ADR 003: Local open-source runtime stack](docs/adr/003-local-open-source-runtime-stack.md) — why each service, its licence and the rejected alternative
- [ADR 004: Web BFF session and typed client](docs/adr/004-web-bff-session-and-typed-client.md) — where tokens live and how the client tracks the API contract
- [All docs](docs/README.md)

## Quick start

### Today

Requirements: Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups
uv run python -m pytest                       # 63 tests, coverage gate 85%
uv run uvicorn app.main:app --reload          # SQLite, development header auth
curl http://127.0.0.1:8000/health/ready
```

In development mode requests authenticate with `X-Tenant-Id` and `X-Actor-Id` headers. With Docker, `docker compose up -d` runs PostgreSQL, Redis, migrations and the API on port 8000. `docker compose --profile workers up -d` also runs the long-lived notification and retention workers, still in development header-auth mode.

Quality gates (same as CI):

```bash
uv run ruff format --check .
uv run ruff check .
uv run python -m pytest
```

Last local run, 2026-11-24: **63 passed, 87.94% coverage**.

### Target (stage 2, DUTH-50)

```bash
docker compose up -d
make seed        # demo tenant + admin, recruiter, hiring manager, interviewer in Keycloak and the app
```

Open the web app at http://localhost:3000 and sign in with a seeded account (`admin@`, `recruiter@`, `manager@` or `interviewer@talentflow.local`, password `dev-demo-password`); the navigation follows the account's role. See [`web/README.md`](web/README.md). The seeded accounts also work with Keycloak's token endpoint for direct API calls.

## Pattern catalog

Status reflects the code at commit `db1f7bc` (2026-11-24). A row moves to `implemented` in the PR that delivers it. Paths are relative to the repository root.

### Implemented

| Pattern | Why it matters | Where in code | Tests | ADR | Status |
| --- | --- | --- | --- | --- | --- |
| Modular monolith, inward dependency rule | Clear module seams without distributed-system cost; framework-free domain | [`app/modules/`](app/modules) | [`tests/architecture/test_dependency_rule.py`](tests/architecture/test_dependency_rule.py) | [001](docs/adr/001-modular-monolith-clean-architecture.md) | implemented |
| Explicit state machine | Illegal lifecycle moves are impossible, not just discouraged | [`app/modules/workflow/domain/candidate_state_machine.py`](app/modules/workflow/domain/candidate_state_machine.py) | [`tests/unit/modules/workflow/test_candidate_transitions.py`](tests/unit/modules/workflow/test_candidate_transitions.py) | [001](docs/adr/001-modular-monolith-clean-architecture.md) | implemented |
| Optimistic concurrency (`expected_version`) | Concurrent edits fail with 409 instead of silently overwriting | [`app/modules/candidates/infrastructure/sqlalchemy_repository.py`](app/modules/candidates/infrastructure/sqlalchemy_repository.py) | [`tests/integration/test_candidate_stage_transition.py`](tests/integration/test_candidate_stage_transition.py) | — | implemented |
| Policy object for staged approval | Approval order and roles drive both the write check and the inbox `can_decide` flag, testable without HTTP | [`app/modules/offers/domain/approval_policy.py`](app/modules/offers/domain/approval_policy.py) | [`tests/unit/modules/offers/test_approval_policy.py`](tests/unit/modules/offers/test_approval_policy.py), [`tests/integration/test_offer_approval.py`](tests/integration/test_offer_approval.py) | — | implemented |
| CQRS-lite query with cursor pagination | Reads skip aggregate loading; stable paging under inserts | [`app/modules/candidates/application/list_candidates.py`](app/modules/candidates/application/list_candidates.py) | [`tests/integration/test_candidate_list_query.py`](tests/integration/test_candidate_list_query.py) | [001](docs/adr/001-modular-monolith-clean-architecture.md) | implemented |
| Transactional outbox | State change and "notify" intent commit atomically; no lost or phantom emails | [`app/modules/notifications/application/outbox_publisher.py`](app/modules/notifications/application/outbox_publisher.py) | [`tests/integration/test_approval_outbox.py`](tests/integration/test_approval_outbox.py), [`tests/unit/modules/notifications/test_outbox_publisher.py`](tests/unit/modules/notifications/test_outbox_publisher.py) | [002](docs/adr/002-transactional-outbox.md) | implemented |
| Leased worker with retry and dead letter | Crashed workers' jobs are reclaimed; poison jobs stop retrying | [`app/modules/notifications/application/delivery_worker.py`](app/modules/notifications/application/delivery_worker.py) | [`tests/unit/modules/notifications/test_delivery_worker.py`](tests/unit/modules/notifications/test_delivery_worker.py) | [002](docs/adr/002-transactional-outbox.md) | implemented |
| Tenant-scoped RBAC | Every request is checked for tenant membership and role permission | [`app/modules/identity/security.py`](app/modules/identity/security.py) | [`tests/integration/test_tenant_rbac.py`](tests/integration/test_tenant_rbac.py) | — | implemented |
| OIDC JWT validation with JWKS rotation | Standard tokens; signing-key rotation without restarts | [`app/modules/identity/infrastructure/jwt_validator.py`](app/modules/identity/infrastructure/jwt_validator.py) | [`tests/unit/modules/identity/test_jwt_validator.py`](tests/unit/modules/identity/test_jwt_validator.py), [`tests/integration/test_oidc_identity.py`](tests/integration/test_oidc_identity.py) | — | implemented |
| Audit trail with correlation IDs | Who did what, joinable across async work; written in the same transaction | [`app/modules/audit/`](app/modules/audit), [`app/api/audit_router.py`](app/api/audit_router.py) | [`tests/integration/test_tenant_rbac.py`](tests/integration/test_tenant_rbac.py), [`tests/integration/test_candidate_stage_transition.py`](tests/integration/test_candidate_stage_transition.py) | — | implemented |
| Fail-fast configuration, redacted secrets | Unsafe production config is rejected at startup; secrets never print | [`app/shared/settings.py`](app/shared/settings.py) | [`tests/unit/test_settings.py`](tests/unit/test_settings.py) | — | implemented |
| Distributed rate limiting | Limits hold across API replicas; trusted-proxy aware | [`app/shared/rate_limit.py`](app/shared/rate_limit.py) | [`tests/unit/test_rate_limit.py`](tests/unit/test_rate_limit.py) | — | implemented |
| Health probes, Prometheus metrics, JSON logs, trace propagation | Operable from day one: readiness, RED metrics, correlated logs | [`app/shared/observability.py`](app/shared/observability.py), [`app/api/health_router.py`](app/api/health_router.py) | [`tests/unit/test_health.py`](tests/unit/test_health.py) | — | implemented |
| Safe file upload (signature check, malware-scan port, private storage) | Uploaded CVs are untrusted input | [`app/modules/attachments/application/attachment_service.py`](app/modules/attachments/application/attachment_service.py), [`app/modules/attachments/infrastructure/filesystem_storage.py`](app/modules/attachments/infrastructure/filesystem_storage.py) | [`tests/integration/test_candidate_attachments.py`](tests/integration/test_candidate_attachments.py), [`tests/unit/modules/attachments/test_filesystem_storage.py`](tests/unit/modules/attachments/test_filesystem_storage.py) | — | implemented |
| Capability URL (revocable iCalendar feed, hashed token) | Calendar clients cannot send auth headers; the URL is the credential | [`app/modules/calendar/application/calendar_subscription.py`](app/modules/calendar/application/calendar_subscription.py) | [`tests/integration/test_calendar_subscriptions.py`](tests/integration/test_calendar_subscriptions.py) | — | implemented |
| Retention policy, legal hold, PII purge | Data minimization with a legal override, audited | [`app/modules/retention/application/retention.py`](app/modules/retention/application/retention.py) | [`tests/integration/test_candidate_retention.py`](tests/integration/test_candidate_retention.py) | — | implemented |
| PII-free reporting read model | Analytics without exposing candidate data | [`app/modules/reporting/application/pipeline_report.py`](app/modules/reporting/application/pipeline_report.py) | [`tests/integration/test_pipeline_report.py`](tests/integration/test_pipeline_report.py) | — | implemented |
| Versioned schema migrations | Reviewable, repeatable schema changes; no `create_all` in production | [`migrations/versions/`](migrations/versions) | CI migration job in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | — | implemented |
| CI quality and security gates | Lint, tests, coverage, image smoke, CodeQL, Trivy on every PR | [`.github/workflows/ci.yml`](.github/workflows/ci.yml), [`.github/workflows/security.yml`](.github/workflows/security.yml) | the workflows themselves | — | implemented |

### Planned

| Pattern | Why it matters | Where in code | Tests | ADR | Status |
| --- | --- | --- | --- | --- | --- |
| Module-owned routers and persistence | Boundaries enforced, not just foldered (DUTH-45) | — | — | [001](docs/adr/001-modular-monolith-clean-architecture.md) | planned — stage 2 |
| RFC 9457 Problem Details | One machine-readable error contract (DUTH-46) | — | — | — | planned — stage 2 |
| Long-running workers, graceful shutdown, advisory-lock scheduling (DUTH-47) | No lost leases on deploy; one retention run at a time | [`app/shared/worker_runtime.py`](app/shared/worker_runtime.py), [`app/workers/retention.py`](app/workers/retention.py) | [`tests/unit/test_worker_runtime.py`](tests/unit/test_worker_runtime.py), [`tests/unit/modules/notifications/test_delivery_worker.py`](tests/unit/modules/notifications/test_delivery_worker.py) | — | implemented |
| SMTP adapter to Mailpit (DUTH-48) | Email visible locally without a provider account | [`app/modules/notifications/infrastructure/smtp_email.py`](app/modules/notifications/infrastructure/smtp_email.py) | [`tests/integration/test_smtp_email.py`](tests/integration/test_smtp_email.py) | [003](docs/adr/003-local-open-source-runtime-stack.md) | implemented |
| S3 storage with presigned downloads (DUTH-49) | Bytes never stream through the API; short-lived links after authz | [`app/modules/attachments/infrastructure/s3_storage.py`](app/modules/attachments/infrastructure/s3_storage.py) | [`tests/integration/test_seaweedfs_s3.py`](tests/integration/test_seaweedfs_s3.py), [`tests/integration/test_candidate_retention.py`](tests/integration/test_candidate_retention.py) | [003](docs/adr/003-local-open-source-runtime-stack.md) | implemented |
| One-command stack and Keycloak (DUTH-50) | Runnable by anyone with real OIDC tokens and seeded roles | — | — | [003](docs/adr/003-local-open-source-runtime-stack.md) | planned — stage 2 |
| Browser OIDC (code + PKCE) through a BFF session, generated typed API client (DUTH-51) | No tokens in the browser; client and API cannot drift | [`web/src/lib/auth/`](web/src/lib/auth), [`web/src/lib/api/`](web/src/lib/api) | [`web/src/lib/auth/auth-service.test.ts`](web/src/lib/auth/auth-service.test.ts), [`web/src/lib/api/bff-proxy.test.ts`](web/src/lib/api/bff-proxy.test.ts) | [004](docs/adr/004-web-bff-session-and-typed-client.md) | implemented |
| Conflict-aware UI for optimistic locking (DUTH-52) | Users see "changed by someone else" instead of losing work; illegal moves are not droppable | [`web/src/components/pipeline/`](web/src/components/pipeline), [`web/src/lib/pipeline/`](web/src/lib/pipeline) | [`web/src/components/pipeline/pipeline-board.test.tsx`](web/src/components/pipeline/pipeline-board.test.tsx), [`web/src/lib/pipeline/stages.test.ts`](web/src/lib/pipeline/stages.test.ts) | — | implemented |
| End-to-end tests against the real stack (DUTH-57) | The hiring flow is proven in a browser on every PR | — | — | — | planned — stage 4 |
| Versioned event envelope and AsyncAPI catalog (DUTH-58) | Explicit integration contracts and evolution rules | — | — | planned with DUTH-58 | planned — stage 5 |
| Outbox relay to RabbitMQ, inbox dedup, DLQ (DUTH-59) | At-least-once delivery, exactly-once effect | — | — | [003](docs/adr/003-local-open-source-runtime-stack.md) | planned — stage 5 |
| Idempotency keys (DUTH-60) | Safe client retries for POST commands | — | — | — | planned — stage 5 |
| ETag / If-Match conditional requests (DUTH-61) | HTTP-native optimistic concurrency | — | — | — | planned — stage 5 |
| Signed outbound webhooks with SSRF guard (DUTH-62) | Verifiable integrations that cannot reach internal hosts | — | — | — | planned — stage 5 |
| Public self-apply with abuse controls (DUTH-63) | Handling anonymous, untrusted input and consent | — | — | — | planned — stage 5 |
| Saga / process manager with compensation (DUTH-64) | Multi-step workflows that undo cleanly on failure | — | — | planned with DUTH-64 | planned — stage 6 |
| Feature flags via OpenFeature + flagd (DUTH-65) | Per-tenant rollout and kill switches without redeploy | — | — | [003](docs/adr/003-local-open-source-runtime-stack.md) | planned — stage 6 |
| Search read projection in OpenSearch (DUTH-66) | Full-text search, rebuildable with zero downtime | — | — | [003](docs/adr/003-local-open-source-runtime-stack.md) | planned — stage 7 |
| PostgreSQL Row-Level Security (DUTH-67) | Tenant isolation even when a query forgets its predicate | — | — | — | planned — stage 7 |
| Envelope encryption and crypto-shredding with OpenBao (DUTH-68) | PII unreadable at rest; deletion by destroying keys | — | — | [003](docs/adr/003-local-open-source-runtime-stack.md) | planned — stage 7 |
| Data subject access export (DUTH-69) | Privacy rights as a product feature | — | — | — | planned — stage 7 |
| Hash-chained, tamper-evident audit (DUTH-70) | Detects edited or deleted audit rows | — | — | — | planned — stage 7 |
| LLM gateway with guardrails and offline evals (DUTH-71) | AI behind one port: redaction, budgets, audit, testable | — | — | planned with DUTH-71 | planned — stage 8 |
| AI resume parsing with human confirmation (DUTH-72) | Assistive AI, a human decides | — | — | — | planned — stage 8 |
| Semantic matching with pgvector (DUTH-73) | Embeddings in the system of record; advisory scores only | — | — | [003](docs/adr/003-local-open-source-runtime-stack.md) | planned — stage 8 |
| Cited feedback summaries (DUTH-74) | Summaries traceable to their sources | — | — | — | planned — stage 8 |
| Error tracking with PII scrubbing (DUTH-75) | Crashes reported without leaking candidate data | — | — | [003](docs/adr/003-local-open-source-runtime-stack.md) | planned — stage 9 |
| SLO-based load tests (DUTH-76) | Performance claims backed by a baseline | — | — | — | planned — stage 9 |
| SBOM, image signing, licence policy (DUTH-77) | Verifiable supply chain | — | — | — | planned — stage 9 |
| STRIDE threat model and audit (DUTH-78) | Security reasoning written down and checked | — | — | — | planned — stage 9 |

## Domain at a glance

| Context | Responsibility |
| --- | --- |
| Organization | tenants, memberships, requisitions |
| Candidates | case creation, list and filter, lifecycle transitions |
| Interviews | scheduling, one structured feedback per interview |
| Offers | hiring manager → tenant admin approval, immutable decisions |
| Notifications | outbox materialization, email delivery with retry |
| Audit, Attachments, Calendar, Reporting, Retention | evidence, secure documents, iCalendar feeds, PII-free reports, data retention |

Candidate lifecycle: `applied → screening → interviewing → offer_pending_approval → offer_approved → hired`, with `offer_rejected`, `rejected` and `withdrawn` exits. See [architecture](docs/architecture.md#5-candidate-workflow-and-concurrency).

## Configuration notes

- Settings are validated at startup (`app/shared/settings.py`). With `APP_ENV=production` the app requires `AUTH_MODE=oidc_jwt`, PostgreSQL, Redis, explicit HTTPS CORS origins, HTTPS OIDC and calendar URLs, an absolute attachment root and ClamAV scanning.
- Variable names are listed in [`.env.example`](.env.example). Values there are local development defaults only. Never commit real credentials.
- `NOTIFICATION_EMAIL_ADAPTER=smtp` is the local default and sends to Mailpit at `mailpit:1025`; set `NOTIFICATION_EMAIL_ADAPTER=sendgrid` with `SENDGRID_API_KEY` to use SendGrid instead. `NOTIFICATION_FROM_EMAIL` is always required.

## Repository layout

```text
app/            FastAPI app, modules (domain / application / infrastructure), shared kernel
migrations/     Alembic revisions
tests/          unit, integration and architecture tests
web/            Next.js web app (BFF session, generated API client)
docs/           architecture, roadmap, ADRs, runbooks
scripts/        PostgreSQL backup/restore, demo seed, OpenAPI export
infra/opentofu/ legacy AWS foundation — out of scope, not maintained
```
