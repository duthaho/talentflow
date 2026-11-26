# ADR-005: Database-backed idempotency keys for POST commands

Status: Accepted (DUTH-60, Phương-CTO's approved issue contract).
Date: 2026-11-26.
Issue: DUTH-60.

Amended by [ADR-007](007-conditional-requests.md): candidate stage PATCH support,
conditional-command header fingerprints, and stored ETag responses.

## Context

Clients need to retry commands after losing a response without creating duplicate
business writes, audit entries or outbox events. Existing application handlers own
their unit-of-work commits. Multiple API processes must coordinate through the
database; an in-memory lock cannot provide that guarantee.

## Decision

`CommandRoute` in `app/api/idempotency.py` adds an optional `Idempotency-Key`
dependency after the endpoint's existing authentication and permission dependencies.
The dependency and handler share FastAPI's cached request session. The guard is
declared in the endpoint signature so included routers retain it when FastAPI
rebuilds dependency graphs. Domain/application code remains unaware of it.

| POST command | Key support |
| --- | --- |
| Requisition, candidate, interview, feedback, offer, approval | Supported |
| `/v1/retention/purge` | Supported; replay the purge summary |
| `/v1/tenants` | Ignored: tenant/actor bootstrap |
| `/v1/calendar-subscriptions` | Ignored: response contains a bearer secret |
| `/v1/candidate-cases/{candidate_case_id}/attachments` | Ignored: multipart upload |

PATCH, PUT, GET and public careers application routes are outside the default contract.
Excluded POST operations describe the exclusion in OpenAPI. Requests without a
key retain their existing behavior. Replays always reauthenticate and pass the
route's current permission dependencies; revoked roles or membership return 403.

DUTH-126 amendment: a command route may explicitly opt in with
`openapi_extra={"x-idempotency-key": True}`. The requisition publication PATCH uses
this metadata to share the same reservation, authorization, completion and replay
handling. Other non-POST routes retain their existing behavior. The generated
OpenAPI includes the optional key header for the opted-in route.

Keys contain 1–255 visible ASCII characters (0x21–0x7E); malformed keys return 400
RFC 9457 Problem Details. The unique scope is `(tenant_id, actor_id, key)`, so the
same key from another principal or tenant executes independently. A fingerprint
is SHA-256 of a canonical JSON tuple containing method, route template, resolved
path parameters and parsed JSON body. Object keys are sorted, separators compact,
and encoding UTF-8. JSON whitespace and object property order do not matter;
array order, explicit values, absent fields and numeric representation do.

The guard inserts an `in_progress` reservation with `INSERT ... ON CONFLICT DO
NOTHING` in the request session. PostgreSQL's unique index serializes competing
inserts across API processes. A transaction-local five-second `lock_timeout`
bounds the wait. The handler's unit-of-work commits the reservation and business
writes together. A concurrent duplicate either waits then replays, or receives
409 Problem Details with `Retry-After: 1` while the reservation is in progress
(including lock timeout). A different fingerprint returns 422 Problem Details.

After successful response serialization, a short follow-up transaction records
the JSON body, status and only `Content-Type` and `Location`, marking the row
`completed`. Replays return those values plus `Idempotent-Replayed: true`. Cookies,
authorization and correlation headers are never stored. Only 2xx responses are
stored. A failed handler rolls back its uncommitted reservation and writes, so
4xx/5xx requests may retry with the same key. A failure **after** the business
commit retains the reservation to prevent duplicate execution.

`IDEMPOTENCY_KEY_TTL_SECONDS` defaults to 86400 and must be positive. Expired rows
count as absent and are removed on key access. The existing scheduled retention
worker also purges expired rows in batches bounded by `RETENTION_WORKER_BATCH_SIZE`,
with `FOR UPDATE SKIP LOCKED` on PostgreSQL. Cleanup runs even without tenant
retention policies. Response bodies may contain application PII; they have the
same database access protections and remain physically stored until access or a
scheduled cleanup removes them. Keys are client-generated opaque values and must
not contain secrets or PII.

## Consequences and alternatives

- A process crash between the business commit and response storage leaves an
  `in_progress` row. Retries receive 409 until expiry. This consciously prefers
  preventing duplicate execution to automatically rerunning an uncertain command.
- TTL starts at reservation. Reuse after expiry is a new execution; callers must
  choose a TTL longer than their command duration and retry window. There is no
  exactly-once guarantee beyond that window, or for external storage side effects.
- SQLite supports local functional tests with its native conflict insert. Real
  cross-process concurrency and lock-timeout guarantees require PostgreSQL, tested
  with two API instances and independent connection pools.
- Redis was rejected: its reservation cannot commit atomically with PostgreSQL
  business data. A process-local mutex cannot coordinate replicas. Moving all
  application commits into an HTTP transaction would unnecessarily broaden scope.

## Verification and rollback

`tests/integration/test_idempotency.py` covers replay, mismatch, malformed keys,
principal/tenant isolation, revoked permission, expiry, failure rollback and the
post-commit crash window. `tests/integration/test_idempotency_postgres.py` exercises
parallel candidate and approval commands, lock timeout, one execution, and no
duplicate audit/outbox effects. Run it with a disposable migrated PostgreSQL
`DATABASE_URL`. Unit tests cover fingerprints, header allowlisting, TTL validation,
bounded cleanup and migration upgrade/downgrade.

The expand-only Alembic revision `d60a001` adds one table and its unique scope and
expiry indexes. Deploy the migration before the API/worker. Roll back application
code before downgrading; downgrade drops the table and its cached responses, so
previous keys then lose their replay protection.

## Revisit when

Revisit response finalization if command handlers adopt an outer transaction, or
when public application and multipart commands need a separate retry contract.
