# TalentFlow

TalentFlow is a **multi-tenant HR candidate workflow and case-management platform** built as a production-oriented enterprise showcase. It manages candidate cases from application through interview and staged offer approval while enforcing tenant isolation, role-based access, auditability, optimistic concurrency, and reliable asynchronous notification delivery.

> **Architecture style:** modular monolith, Clean/Hexagonal boundaries, CQRS-lite, transactional outbox, and idempotent background delivery.

## Why this project exists

This repository demonstrates how to start an enterprise workflow system without prematurely creating microservices or a distributed monolith. The application has explicit bounded contexts and ports so individual capabilities can be extracted when operational evidence justifies it.

## Implemented capabilities

- **Organization & tenancy** — tenant bootstrap, tenant-admin membership, requisitions, tenant-scoped authorization, and audit records.
- **Candidate cases** — tenant-owned requisition validation, normalized tenant-unique email, cursor pagination, filtering, lifecycle state machine, and optimistic locking.
- **Interviews** — interviewer assignment, scheduling, one structured feedback record per interview, and interviewer-only submission.
- **Offers** — offer creation only from `interviewing`, ordered hiring-manager then tenant-admin approval, immutable approval decisions, and candidate-stage synchronization.
- **Reliable notifications** — transactional outbox, idempotent outbox materialization, SendGrid adapter, retry policy, and dead-letter state.
- **Auditability** — tenant-scoped audit trail with correlation IDs for business commands.

## Architecture at a glance

```text
                         +-----------------------+
                         | FastAPI presentation  |
                         | routes, DTOs, auth    |
                         +-----------+-----------+
                                     |
                                     v
+----------------------------------------------------------------+
| Application layer: commands, queries, ports, transaction scope |
+----------------------------------------------------------------+
             | domain aggregates/policies       | ports/protocols
             v                                  v
+---------------------------+      +-----------------------------+
| Domain layer              |      | Infrastructure adapters     |
| CandidateCase, Offer,     |      | SQLAlchemy, SendGrid,       |
| Interview, approval rules |      | workers, outbox persistence |
+---------------------------+      +-----------------------------+
                                     |
                                     v
                           PostgreSQL / external email provider
```

The primary dependency rule is inward: domain code must not import FastAPI, SQLAlchemy, Pydantic, or provider SDKs. Application handlers coordinate business rules through ports; infrastructure implements those ports. Architecture tests enforce this rule for the modularized contexts.

Read the detailed design: [docs/architecture.md](docs/architecture.md).

## Bounded contexts

| Context | Responsibility | Key patterns |
| --- | --- | --- |
| Organization | tenants, memberships, requisitions | application service, repository, unit of work |
| Candidates | case creation, search, lifecycle transitions | aggregate, state machine, optimistic locking, CQRS-lite |
| Interviews | scheduling and structured feedback | application command, authorization policy |
| Offers | staged approvals and downstream events | aggregate, policy object, immutable decision, transactional outbox |
| Notifications | outbox publishing and email delivery | ports/adapters, idempotency, retry/dead-letter worker |
| Audit | tenant-scoped evidence of business actions | append-only audit records, query adapter |

## Candidate workflow

```text
applied -> screening -> interviewing -> offer_pending_approval
                                           |              |
                                           v              v
                                   offer_rejected   offer_approved -> hired
```

Transitions are explicit. The write side checks the expected aggregate version and rejects stale commands rather than overwriting a concurrent update.

## Reliability model

Offer approval persists the business state, immutable `ApprovalDecision`, and versioned `offer.approval_recorded.v1` outbox event in the same database transaction. Publishers and workers therefore run with **at-least-once** semantics. Consumers must be idempotent; notification materialization uses a durable unique outbox-event relationship to prevent duplicate delivery records.

See [ADR-002](docs/adr/002-transactional-outbox.md).

## Security posture

- Every protected request is tenant-scoped and checks membership plus role permissions.
- Candidate email uniqueness is enforced per tenant both in application validation and the database schema.
- Database writes use tenant predicates where aggregate isolation matters.
- Audit records retain actor, tenant, aggregate, action, correlation ID, and scoped metadata.
- Provider credentials are configuration only; never commit API keys.

### Authentication and configuration

Production requires `AUTH_MODE=oidc_jwt`. The API verifies the JWT signature, issuer, audience, and JWKS signing key before resolving tenant membership and RBAC. `X-Tenant-Id` and `X-Actor-Id` remain available only in explicit development/test header-auth mode.

Runtime configuration is validated at process startup. Production must provide a PostgreSQL `DATABASE_URL`, explicit HTTPS `CORS_ALLOWED_ORIGINS`, and OIDC issuer/audience/JWKS coordinates. The app never creates tables in production; apply the schema first with `uv run alembic upgrade head`.

Provider credentials are typed as secrets and redacted from settings representations. `SENDGRID_API_KEY` and `NOTIFICATION_FROM_EMAIL` are an all-or-nothing pair, supplied through deployment secrets rather than repository files.

## Local development

Requirements: Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups
uv run uvicorn app.main:app --reload
```

Health and operational probes:

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
curl http://127.0.0.1:8000/metrics
```

`/health/live` verifies process liveness; `/health/ready` verifies database connectivity. `/metrics` exposes Prometheus metrics for HTTP traffic/latency, command conflicts, outbox backlog, delivery outcomes, dead letters, and worker claims. Request logs are structured JSON, include `correlation_id`, and the API propagates OpenTelemetry trace context.

Run quality gates:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

The project is configured for PostgreSQL via environment settings. A `docker-compose.yml` manifest is included for local infrastructure when Docker is available.

## Notification worker

Configure deployment secrets:

```bash
SENDGRID_API_KEY=<provider-secret>
NOTIFICATION_FROM_EMAIL=<verified-sender>
```

Then run one bounded worker cycle (typically under a deployment scheduler or worker supervisor):

```bash
uv run python -m app.modules.notifications.application.run_email_worker
```

The worker first materializes pending outbox events, then claims delivery rows with a durable lease. A crashed worker's expired lease is reclaimed; only the lease holder can finalize the attempt. The sender must be verified by SendGrid. Recipient resolution requires `users.email`; failed deliveries are retried and eventually marked `dead_letter`.

For an outbox-only operational cycle:

```bash
uv run python -m app.modules.notifications.application.run_outbox_publisher
```

## Quality evidence

The current suite verifies tenant isolation, RBAC, candidate lifecycle invariants, concurrency behavior, interview authorization, offer approval ordering, transactional outbox persistence, retry behavior, SendGrid request mapping, and architecture dependency rules.

- Pytest coverage threshold: **85%**
- Last verified local result: **41 tests passed; 93.44% coverage**

## Decisions and further reading

- [Architecture design](docs/architecture.md)
- [ADR-001: Modular monolith and Clean Architecture](docs/adr/001-modular-monolith-clean-architecture.md)
- [ADR-002: Transactional outbox and at-least-once delivery](docs/adr/002-transactional-outbox.md)

## Production-readiness roadmap

The architecture foundation, OIDC/JWT identity, Alembic migrations, configuration hardening, and operational telemetry are implemented. A real production rollout still requires rate limits, backup and recovery procedures, CI/CD with vulnerability scanning, deployment-specific infrastructure validation, and live verification against a real OIDC provider and verified email sender.
