# TalentFlow architecture

This document describes the architecture **as built today** (baseline commit `db1f7bc`, 2026-11-24) and the **target** architecture of the [roadmap](roadmap.md). Every target element is labelled with the stage that delivers it. Runtime services are chosen in [ADR 003](adr/003-local-open-source-runtime-stack.md).

## 1. Thesis

TalentFlow is a multi-tenant HR candidate workflow and case-management platform (ATS). It is a **modular monolith**: one deployable API, background workers built from the same image, one PostgreSQL transactional boundary, and bounded contexts with explicit ports. This avoids distributed transactions and cross-service deployment before the domain, ownership or scale proves a split is worth it ([ADR 001](adr/001-modular-monolith-clean-architecture.md)).

Inside each module, Clean/Hexagonal layering applies and dependencies point inward:

```mermaid
flowchart LR
  P["Presentation<br/>FastAPI routes, Pydantic DTOs"] --> A["Application<br/>commands, queries, ports, transaction scope"]
  A --> D["Domain<br/>aggregates, policies, state machine"]
  I["Infrastructure<br/>SQLAlchemy, SendGrid, ClamAV, storage"] -. implements ports .-> A
```

| Layer | May contain | Must not depend on |
| --- | --- | --- |
| Domain | aggregates, entities, policies, value objects, domain errors | FastAPI, SQLAlchemy, Pydantic, provider SDKs |
| Application | commands, handlers, query services, ports, unit-of-work contracts | HTTP framework, ORM records (`app.shared.models`), provider SDKs |
| Infrastructure | repositories, persistence records, provider clients, workers | presentation concerns |
| Presentation | routes, DTOs, dependency wiring, error mapping | business invariants |

`tests/architecture/test_dependency_rule.py` enforces the domain rule for every module and the application rule for `attachments`, `audit`, `calendar`, `candidates`, `interviews`, `offers`, `organization`, `reporting` and `retention`. It also forbids direct cross-module infrastructure imports and requires each cross-context persistence import to be a documented allow-list entry.

## 2. System context (C4 level 1)

### Current

```mermaid
flowchart TB
  user["HR user<br/>(admin, recruiter, hiring manager, interviewer)<br/>via API client"]
  cal["Calendar client<br/>(Google, Outlook)"]
  tf["TalentFlow<br/>FastAPI modular monolith + workers"]
  idp["OIDC provider<br/>(any; JWKS)"]
  sg["SendGrid<br/>(email, optional)"]
  user -- "HTTPS / JSON, Bearer JWT" --> tf
  cal -- "HTTPS iCalendar feed" --> tf
  tf -- "fetch JWKS" --> idp
  tf -- "HTTPS API" --> sg
```

There is no web UI yet. Authentication is either `oidc_jwt` (production mode) or `development_headers` (`X-Tenant-Id` / `X-Actor-Id`, development and tests only).

### Target

```mermaid
flowchart TB
  staff["HR staff<br/>(admin, recruiter, hiring manager, interviewer)"]
  applicant["Applicant<br/>(public, anonymous)"]
  cal["Calendar client"]
  partner["Tenant webhook endpoint"]
  tf["TalentFlow<br/>web app + API + workers"]
  kc["Keycloak<br/>(identity)"]
  mail["Mailpit<br/>(local SMTP sink)"]
  staff -- "browser, OIDC login" --> tf
  applicant -- "careers page, apply (stage 5)" --> tf
  cal -- "iCalendar feed" --> tf
  tf -- "signed webhooks (stage 5)" --> partner
  tf -- "OIDC, admin API" --> kc
  staff -- "login" --> kc
  tf -- "SMTP (stage 2)" --> mail
```

## 3. Containers (C4 level 2)

### Current

```mermaid
flowchart LR
  client["API client"] --> api["API<br/>FastAPI / Uvicorn"]
  migrate["migrate<br/>alembic upgrade head (one-shot)"] --> pg
  api --> pg[("PostgreSQL 17")]
  api --> redis[("Redis<br/>rate limits")]
  api --> fs[("Attachment volume<br/>local filesystem")]
  api -. "clamscan (when ATTACHMENT_SCAN_MODE=clamav)" .-> clam["ClamAV CLI"]
  ow["notification worker<br/>poll loop: outbox → deliveries"] --> pg
  ew["email worker<br/>poll loop: leased delivery"] --> pg
  ew --> sg["SendGrid"]
  rw["retention worker<br/>scheduled purge + advisory lock"] --> pg
  rw --> fs
```

Workers are long-lived processes built from the API image. They poll with bounded exponential backoff, drain on SIGTERM (releasing email leases if the grace period expires), expose `/health/live`, `/health/ready` and `/metrics`, and record cycle-success and backlog metrics. Retention uses a configurable interval and PostgreSQL advisory lock, so only one replica purges at a time. `docker compose --profile workers up -d` starts the notification and retention services.

### Target

```mermaid
flowchart LR
  subgraph app["TalentFlow (one image for API and workers)"]
    web["web<br/>Next.js (stage 3)"]
    api["api<br/>FastAPI"]
    relay["outbox relay (stage 5)"]
    consumers["consumers: notifications, webhooks,<br/>search projector, saga, AI jobs"]
    sched["scheduled workers<br/>retention (stage 2)"]
  end
  web --> api
  api --> pg[("PostgreSQL + pgvector")]
  api --> redis[("Redis")]
  api --> s3[("SeaweedFS (S3)")]
  api --> clam["ClamAV clamd"]
  api --> flags["flagd (stage 6)"]
  api --> os[("OpenSearch (stage 7)")]
  api --> bao["OpenBao transit (stage 7)"]
  api --> kc["Keycloak"]
  web --> kc
  relay --> pg
  relay --> mq[["RabbitMQ (stage 5)"]]
  mq --> consumers
  consumers --> pg
  consumers --> os
  consumers --> mail["Mailpit"]
  consumers --> llm["Ollama (stage 8)"]
  consumers --> kc
  sched --> pg
  sched --> s3
  app -. "OTLP" .-> otel["OTel Collector"] --> lgtm["Grafana LGTM"]
  app -. "Sentry SDK (stage 9)" .-> gt["GlitchTip"]
```

## 4. Bounded contexts

| Context | Responsibility | Status | Key patterns |
| --- | --- | --- | --- |
| Organization | tenants, memberships, requisitions | implemented | application service, unit of work, audit |
| Identity | JWT validation, actor context, RBAC permissions | implemented | ports/adapters, JWKS rotation |
| Candidates | case creation, list/filter, lifecycle transitions | implemented | aggregate, state machine (`workflow`), optimistic locking, CQRS-lite |
| Interviews | scheduling, scoped interview listing, structured feedback | implemented | authorization policy, application-layer ownership rule, opaque `(scheduled_at, id)` keyset read model, one-feedback-per-interview |
| Offers | staged approvals | implemented | aggregate, policy object, immutable decisions, outbox |
| Notifications | outbox materialization, email delivery | implemented | outbox, leased worker, retry, dead letter |
| Audit | tenant-scoped append-only evidence | implemented | same-transaction audit write; hash chain planned (stage 7) |
| Audit read side | case-scoped timeline | implemented | keyset pagination; metadata is projected through a default-deny PII allowlist |
| Attachments | upload, scan, private storage, download | implemented (filesystem) | file-signature checks, malware-scan port; S3 + presigned URLs planned (stage 2) |
| Calendar | revocable iCalendar feeds | implemented | capability URL, hashed tokens, expiry |
| Reporting | PII-free pipeline read model | implemented | read model |
| Retention | retention policy, legal hold, purge | implemented | bounded purge worker, anonymization |
| Search | candidate full-text search and facets | **planned — stage 7** | event-fed OpenSearch projection, alias swap rebuild |
| Webhooks | tenant subscriptions, signed delivery | **planned — stage 5** | HMAC signing, retry/DLQ, SSRF guard |
| Onboarding saga | hire → employee record, account, day-1 tasks | **planned — stage 6** | process manager, compensation |
| Feature flags | per-tenant/role targeting, kill switches | **planned — stage 6** | OpenFeature, flagd |
| AI assistant | resume parsing, matching, feedback summary | **planned — stage 8** | LLM gateway port, guardrails, eval harness, pgvector |

Known gaps in today's boundaries (fixed by DUTH-45 in stage 2): tenant, candidate, interview and offer routes still live in `app/main.py`, other routers in `app/api/`, and all ORM records are shared in `app/shared/models.py`.

## 5. Candidate workflow and concurrency

```mermaid
stateDiagram-v2
  [*] --> applied
  applied --> screening
  screening --> interviewing
  interviewing --> offer_pending_approval
  offer_pending_approval --> offer_approved
  offer_pending_approval --> offer_rejected
  offer_approved --> hired
  offer_rejected --> rejected
  applied --> rejected
  screening --> rejected
  interviewing --> rejected
  applied --> withdrawn
  screening --> withdrawn
  interviewing --> withdrawn
  offer_pending_approval --> withdrawn
  offer_approved --> withdrawn
  offer_rejected --> withdrawn
  hired --> [*]
  rejected --> [*]
  withdrawn --> [*]
```

Transitions are defined in `app/modules/workflow/domain/candidate_state_machine.py`. Every write carries `expected_version`; the repository issues a version-guarded `UPDATE` and a `rowcount` of 0 becomes a 409 conflict instead of a lost update. Stage 5 adds `ETag`/`If-Match` as an HTTP-native alternative.

Offer approval is ordered by `ApprovalPolicy.standard()`: hiring manager, then tenant admin. The same policy drives the read-side `awaiting_role` and `can_decide` fields, so the approval inbox displays exactly the actions the write path permits. A rejection at either step moves the candidate to `offer_rejected`.

## 6. Command flow and transaction ownership

```mermaid
sequenceDiagram
  participant R as Route
  participant H as Application handler
  participant D as Domain
  participant P as Ports (repo, audit, outbox)
  participant DB as PostgreSQL
  R->>H: command (tenant, actor, correlation id)
  H->>P: load aggregate
  H->>D: apply rule / policy
  H->>P: save (version-guarded), audit, outbox event
  H->>DB: commit (one transaction)
  H-->>R: result or domain error
```

The application handler owns the transaction, so a state change, its audit record and its outbox event commit together or not at all.

## 7. Event flow

### Current: outbox → notification deliveries

```mermaid
flowchart LR
  cmd["Offer decision handler"] -- "same transaction" --> ob[("outbox_events<br/>offer.approval_recorded.v1")]
  ob --> pub["outbox publisher"] -- "unique outbox_event_id" --> nd[("notification_deliveries")]
  nd --> w["email worker<br/>lease, retry"] --> sg["SendGrid"]
  w --> dl["dead_letter after max attempts"]
```

Delivery is **at-least-once**. Idempotency comes from the unique `notification_deliveries.outbox_event_id`; a crashed worker's expired lease is reclaimed and only the lease holder can finalize ([ADR 002](adr/002-transactional-outbox.md)).

### Target: outbox → RabbitMQ → consumers with inbox dedup (stage 5)

```mermaid
flowchart LR
  h["Command handler"] -- "same transaction" --> ob[("outbox")]
  ob --> relay["outbox relay<br/>publisher confirms"]
  relay --> ex{{"RabbitMQ topic exchange<br/>routing key = event type"}}
  ex --> q1["notifications queue"] --> c1["notification consumer"]
  ex --> q2["webhooks queue"] --> c2["webhook dispatcher"]
  ex --> q3["search queue"] --> c3["search projector"]
  ex --> q4["saga queue"] --> c4["onboarding process manager"]
  c1 & c2 & c3 & c4 --> inbox[("inbox table<br/>(consumer, event_id) unique")]
  q1 & q2 & q3 & q4 -. "after N retries" .-> dlq["dead-letter queues"]
```

Each consumer records `(consumer, event_id)` in an inbox table in the same transaction as its side effect, so a redelivered event is applied once. The envelope, event catalog and topology are defined in [ADR 006](adr/006-integration-event-contract.md) and [`docs/events/asyncapi.yaml`](events/asyncapi.yaml). Payloads carry identifiers, not free-text PII.

## 8. Identity and tenancy

### Current

- `AUTH_MODE=oidc_jwt`: the API validates signature, issuer, audience and expiry against the configured JWKS (`app/modules/identity/infrastructure/jwt_validator.py`), refreshing keys once on an unknown `kid`. The token must carry `sub` and a `tenant_id` claim; `sub` is used as the local actor id, then tenant membership and role permissions are checked (`app/modules/identity/security.py`).
- `AUTH_MODE=development_headers`: `X-Tenant-Id` and `X-Actor-Id`, rejected by settings validation in production.
- Every aggregate lookup and write is tenant-scoped in the application; Row-Level Security adds a database-level guard in stage 7.

<!-- permission-matrix:start -->
| Permission | `tenant_admin` | `recruiter` | `auditor` | `hiring_manager` | `interviewer` |
| --- | --- | --- | --- | --- | --- |
| `requisition:create` | ✓ | ✓ |  |  |  |
| `candidate:create` | ✓ | ✓ |  |  |  |
| `candidate:transition` | ✓ | ✓ |  |  |  |
| `candidate:attachment` | ✓ | ✓ |  |  |  |
| `calendar:manage` | ✓ | ✓ |  |  |  |
| `calendar:self` |  |  |  |  | ✓ |
| `interview:manage` | ✓ | ✓ |  |  |  |
| `feedback:submit` |  |  |  |  | ✓ |
| `audit:read` | ✓ | ✓ | ✓ |  |  |
| `report:read` | ✓ | ✓ |  |  |  |
| `tenant:read` | ✓ | ✓ | ✓ | ✓ |  |
| `retention:manage` | ✓ | ✓ |  |  |  |
| `retention:purge` | ✓ | ✓ |  |  |  |
<!-- permission-matrix:end -->

`calendar:self` is scoped to the caller: it permits an interviewer to manage only links whose interviewer is their own authenticated identity, while `calendar:manage` remains the tenant-wide administrative permission.

### Target: login through Keycloak (stages 2–3)

```mermaid
sequenceDiagram
  actor U as User (browser)
  participant W as Web app (Next.js)
  participant K as Keycloak
  participant A as TalentFlow API
  participant DB as PostgreSQL
  U->>W: open app
  W->>K: redirect, authorization code + PKCE
  U->>K: log in (demo realm)
  K-->>W: code
  W->>K: exchange code + verifier
  K-->>W: access token (JWT), refresh token
  W->>A: API call, Authorization: Bearer JWT (sub, tenant_id)
  A->>K: JWKS (cached)
  A->>DB: actor = sub, check tenant membership + role
  A-->>W: response or 401/403 Problem Details
```

Keycloak owns authentication; TalentFlow owns authorization (tenant membership and role permissions stay in the app database). Because the API uses `sub` as the actor id and requires a `tenant_id` claim, the Keycloak realm needs a `tenant_id` protocol mapper and the seed step (DUTH-50) must create each demo user with the same id in Keycloak and the app database. The onboarding saga (stage 6) uses the Keycloak admin API to provision accounts.

The local realm's `tenant_id` mapper is hardcoded only for its single demo tenant; a multi-tenant realm must derive the claim from a user attribute or tenant mapping.

## 9. Persistence

- SQLAlchemy ORM records are persistence models, not domain objects; repositories translate between them.
- A context owns mapped records in `app/modules/<context>/infrastructure/models.py`. Its `persistence.py` publishes only the records that an explicitly allow-listed cross-context dependency needs. The allow-list covers transactional audit writes, identity membership lookup, ownership validation, notification recipient/outbox handling, retention purge, and Reporting's CQRS-lite projection; all other cross-context access uses an application port or an integration event.
- PostgreSQL is the system of record; tests run on SQLite, CI also applies migrations to PostgreSQL.
- The audit timeline uses a `CaseTimelineReader` application port. Its SQLAlchemy adapter has read-only access to candidate existence and attachment ids, with tenant predicates on both the audit rows and attachment subquery. The application handler decodes cursors, assembles pages and applies the metadata allowlist; routers map permissions, errors and response models. Candidate detail and retention reads likewise go through their module repository ports.
- Schema changes go through Alembic (`migrations/versions/`) with expand/contract compatibility. The app creates tables only outside production.
- Database constraints back the invariants: tenant-unique candidate email, one feedback per interview, one decision per approval step, unique outbox materialization.

## 10. Operations (local)

- Probes: `/health/live`, `/health/ready` (database), `/metrics` (Prometheus: HTTP RED, conflicts, outbox backlog, delivery outcomes, dead letters, worker claims).
- Logs: JSON with `correlation_id`. Tracing: FastAPI OpenTelemetry instrumentation propagates trace context; an OTLP exporter, the Collector and Grafana arrive in stage 2 (DUTH-92, after the core compose stack).
- Backups: [backup and restore runbook](runbooks/backup-restore.md).
- Configuration is validated at startup (`app/shared/settings.py`); secrets are typed and redacted. Local credentials are dev-only values in `.env.example`.

## 11. Quality controls

- `ruff format --check`, `ruff check`, `python -m pytest` with coverage ≥ 85%, architecture tests.
- CI (`.github/workflows/ci.yml`): migrations on PostgreSQL, tests, image build, API readiness, worker smoke command. Security (`.github/workflows/security.yml`): CodeQL, Trivy dependency and image scan.
- Last local run (2026-11-24, `uv run python -m pytest`): **63 passed, 87.94% coverage**.

## 12. Service extraction criteria

A module becomes a separate service only with evidence of: materially different scaling or availability needs; an independent release cadence or owning team; a hard security boundary; stable contracts with low cross-context transaction coupling; or better operational economics than in-process integration. Likely order if justified: Notifications, then read projections (Reporting, Search), then AI jobs. Stage 5's RabbitMQ events create the seam; they do not by themselves justify a split.
