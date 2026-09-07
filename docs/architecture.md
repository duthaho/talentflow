# TalentFlow Architecture

## 1. Purpose and architectural thesis

TalentFlow is a multi-tenant HR candidate workflow and case-management platform. Its purpose is to demonstrate an enterprise design that is credible in production without starting as a network-distributed system.

The system starts as a **modular monolith**: one deployable application, one transactional relational database boundary, and independently structured bounded contexts. This avoids distributed transactions, cross-service deployment coordination, and operational overhead before the domain, ownership, scale, or availability profile proves that separation is worthwhile.

The design applies Clean Architecture / Hexagonal Architecture within each modularized context:

```text
presentation -> application -> domain
                    |
                    v
                  ports <-> infrastructure adapters
```

Dependencies point inward. The domain is framework-independent. The application coordinates a use case through protocols. Infrastructure contains SQLAlchemy and provider details. Presentation owns FastAPI, Pydantic DTOs, HTTP mapping, and request authentication context.

## 2. System context

```text
+----------------------+       HTTPS        +-------------------------+
| Browser / API client | -----------------> | TalentFlow FastAPI app  |
+----------------------+                    +------------+------------+
                                                          |
                         +--------------------------------+------------------------------+
                         |                                |                              |
                         v                                v                              v
                +----------------+             +-------------------+         +------------------+
                | PostgreSQL     |             | Outbox publisher   |         | Email worker     |
                | system of      |             | durable event ->   |         | retry/dead-letter|
                | record         |             | delivery intent    |         | -> SendGrid      |
                +----------------+             +-------------------+         +------------------+
```

The PostgreSQL database is the system of record. External email is never part of the business transaction. Instead, a committed outbox event represents the durable intent to notify.

## 3. Bounded contexts

### Organization

**Responsibility:** bootstrap a tenant, establish the initial tenant administrator membership, create requisitions, and record organization-level audit evidence.

**Application services:** `OrganizationService`, `CreateTenantCommand`, `CreateRequisitionCommand`.

**Invariants:**

- Tenant slug is globally unique.
- The bootstrap administrator exists as a user and has a `tenant_admin` membership for the new tenant.
- Requisitions belong to the calling actor's tenant.

### Candidates

**Responsibility:** candidate-case creation, tenant-scoped search, lifecycle transitions, email normalization, and concurrency protection.

**Domain aggregate:** `CandidateCase`.

**Invariants:**

- Candidate email is normalized and unique within a tenant.
- Requisition must belong to the tenant.
- Lifecycle changes must be allowed by the candidate state machine.
- A write requires an `expected_version`; stale writes are rejected.

**Read/write split:** commands use `CreateCandidateHandler` and `TransitionCandidateHandler`. `ListCandidatesHandler` is a CQRS-lite query path that returns an optimized page DTO without loading a write aggregate.

### Interviews

**Responsibility:** schedule interviews and capture structured interviewer feedback.

**Domain entity:** `Interview`.

**Invariants:**

- The candidate case and assigned interviewer must belong to the tenant.
- The assigned user must have the `interviewer` membership role.
- Only the assigned interviewer may submit feedback.
- Each interview allows one feedback record.

### Offers

**Responsibility:** create offers, enforce staged approval, preserve immutable decisions, synchronize candidate lifecycle, and emit integration events.

**Domain aggregate:** `Offer`.

**Policy object:** `ApprovalPolicy.standard()` requires a `hiring_manager` decision followed by a `tenant_admin` decision.

**Invariants:**

- Offer creation begins only when a candidate is in `interviewing`.
- One offer belongs to one candidate case.
- Approval role and step ordering are enforced by domain policy.
- Offer and candidate updates use version checks.
- Decisions are immutable; each approval step has one decision.

### Notifications

**Responsibility:** transform committed outbox events into delivery work, send email through a provider adapter, and retry failures.

This context currently has a worker boundary and a SendGrid adapter. It is the most likely early extraction candidate because delivery workload, availability objectives, and provider concerns can evolve independently from the workflow core.

### Audit

**Responsibility:** retain tenant-scoped, append-only evidence of material actions and expose a read-side API adapter.

Audit records retain tenant, actor, action, aggregate type/id, correlation ID, metadata, and creation time. Commands write audit records in the same application transaction as their state change.

## 4. Layering and dependency rules

| Layer | May contain | Must not depend on |
| --- | --- | --- |
| Domain | aggregates, entities, policies, domain errors, value objects | FastAPI, SQLAlchemy, Pydantic, SendGrid/provider SDKs |
| Application | commands, handlers, query services, ports, unit-of-work contracts | HTTP framework, ORM records, provider SDKs |
| Infrastructure | SQLAlchemy repositories, persistence records, provider clients, workers | presentation concerns |
| Presentation | routes, request/response DTOs, dependency injection, error mapping | business invariants or direct business-state mutation |

`tests/architecture/test_dependency_rule.py` programmatically checks that the modularized application and domain layers do not import forbidden framework or persistence dependencies.

## 5. Command flow and transaction ownership

A business command follows this lifecycle:

```text
HTTP route
  -> validate transport DTO
  -> build command with tenant, actor, correlation metadata
  -> application handler
      -> load aggregate/read through a port
      -> evaluate domain rule or policy
      -> persist through a port
      -> record audit/outbox work through ports
      -> commit unit of work
  -> map result or domain error to HTTP response
```

The **application handler owns the transaction boundary**. This keeps an endpoint from accidentally committing only one part of a state transition. Examples:

- Candidate creation writes candidate case and audit record together.
- Candidate transition writes version-guarded stage update and transition audit record together.
- Offer decision writes offer state, candidate state when final/rejected, immutable approval decision, and outbox event together.

## 6. Candidate state machine and concurrency

```text
applied -> screening -> interviewing -> offer_pending_approval
                                           |              |
                                           v              v
                                   offer_rejected   offer_approved -> hired
```

Terminal and alternate transitions such as rejection and withdrawal are explicitly enumerated in the state machine. A candidate command carries `expected_version`. Repositories issue version-guarded updates; `rowcount != 1` becomes a conflict instead of silent lost update.

This is optimistic concurrency control: concurrent callers can read, but only the caller operating on the current version succeeds.

## 7. Offer approval and transactional outbox

### Approval flow

```text
interviewing candidate
  -> create pending offer + candidate.offer_pending_approval
  -> hiring_manager approves step 1
  -> tenant_admin approves step 2
  -> offer approved + candidate.offer_approved
```

A rejection at either step rejects the offer and moves the candidate to `offer_rejected`.

### Reliable event flow

```text
Offer decision handler
   | single database transaction
   +-> Offer update
   +-> Candidate update where needed
   +-> ApprovalDecision insert
   +-> OutboxEvent(topic=offer.approval_recorded.v1)

Outbox publisher -> NotificationDelivery (idempotent materialization)
Delivery worker -> SendGrid adapter -> delivered | retry | dead_letter
```

The system intentionally provides **at-least-once**, not exactly-once, delivery. The outbox publisher or worker may replay work after failure. Idempotency is enforced with durable uniqueness (`notification_deliveries.outbox_event_id`) so replay cannot create another delivery record for the same outbox event.

This follows the [AWS transactional outbox pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html).

## 8. Tenancy, authorization, and audit

All protected request paths obtain an `ActorContext` containing tenant, actor, and role. The current development identity adapter validates `X-Tenant-Id` and `X-Actor-Id` against memberships and role permissions. Every aggregate lookup and business write uses tenant scope.

This header mechanism is not production authentication. Production deployment requires an OIDC/JWT adapter with signature validation, issuer/audience validation, expiry checks, key rotation, and mapping of external subject claims to local membership.

Correlation IDs are accepted through `X-Correlation-Id`; a generated identifier provides a fallback for write commands. They let audit and operational events be joined across asynchronous processing.

## 9. Persistence strategy

SQLAlchemy ORM records are persistence models, not domain aggregates. Infrastructure repositories translate records into domain entities or application read DTOs. PostgreSQL is the intended production database; SQLite is used in tests.

The project currently initializes schema metadata at application startup for development/test convenience. A production rollout must replace this with an explicit migration pipeline (for example Alembic), migration review, backup, and rollback procedures.

## 10. Operational model

### HTTP process

The API runs through Uvicorn and exposes `/health`. The process serves synchronous command/query endpoints.

### Background processes

- **Outbox publisher:** materializes pending outbox events into notification deliveries.
- **Email worker:** claims delivery work, sends through SendGrid, applies retry scheduling, and marks exhausted work as `dead_letter`.

### Configuration and secrets

Provider credentials are loaded from environment settings. Secrets must be supplied through deployment secret management; they must never enter Git, fixtures, logs, ADRs, or README examples.

## 11. Quality controls

The repository enforces:

- Ruff formatting and linting.
- Pytest integration/unit tests.
- Coverage threshold of 85%.
- Architecture dependency tests.
- Database constraints for tenant-scoped candidate email, feedback cardinality, approval step cardinality, and notification materialization idempotency.

The last local verification ran **41 tests** with **93.44% coverage**.

## 12. Service extraction criteria

No context should be split merely because it has a folder. A module becomes a microservice only when evidence supports the operational cost:

1. materially different scaling or availability needs;
2. an independent release cadence or dedicated owning team;
3. a hard security/isolation boundary;
4. stable integration contracts and low cross-context transaction coupling; or
5. operational economics better than in-process integration.

Likely order if justified: Notifications first, then Reporting/read projections, and finally isolated workflow capabilities. Candidate and Offer remain in-process while their aggregate boundaries and approval contracts evolve.

## 13. Production gap register

The architecture is intentionally production-oriented, not a claim that every deployment control is already provisioned. Before public production launch, complete:

- OIDC/JWT authentication and authorization integration;
- managed PostgreSQL, encrypted backups, restore exercises, and migration pipeline;
- secrets manager and credential rotation;
- structured logs, metrics, tracing, alerting, and correlation propagation;
- API rate limits, CORS policy, request-size limits, and security headers;
- CI/CD with dependency/license/vulnerability scanning and deployment promotion;
- real provider sender verification and end-to-end email delivery verification;
- container/runtime health, readiness, and graceful worker shutdown verification.
