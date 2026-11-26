# ADR-007: Aggregate version preconditions over HTTP

Status: Accepted (DUTH-61, Phương-CTO's approved issue contract).
Date: 2026-11-26.

## Context

Candidate stage transitions and offer decisions already protect writes with an
aggregate version and an atomic compare-and-update. HTTP clients should be able
to express that precondition without coupling command bodies to version fields.
Legacy clients using `expected_version` must continue to work.

## Decision

`GET /v1/candidate-cases/{id}` and `GET /v1/offers/{id}` return a strong `ETag`
containing the quoted aggregate version, for example `"3"`. The corresponding
`PATCH .../stage` and `POST .../approvals` commands accept `If-Match` and return
the updated ETag. Lists have no ETag; other endpoints ignore `If-Match`.

The validator identifies the aggregate revision relevant to writes, rather than
a hash of a response projection. Every aggregate mutation must increment that
version, including changes made through other workflows. Read projections can
include related decisions, role-derived permissions, or requisition metadata;
the tag does not validate changes to those independently owned resources. These
responses remain `private, no-store`: this is a write-concurrency contract, not
a representation cache validator. Conditional GET (`If-None-Match`/304) is out
of scope. A future caching contract needs representation-specific validators.

| Preconditions | Result |
| --- | --- |
| Header matches current version | Execute against that exact version |
| Header does not match | 412 `precondition-failed`, current ETag and `current_version` |
| Body only | Existing behavior, including 409 `version-conflict` on mismatch |
| Header and body agree | Execute; a stale header still yields 412 |
| Header and body disagree | 400 `invalid-precondition` |
| Neither supplied | 428 `precondition-required`, `Cache-Control: no-store` |
| Weak, unquoted or malformed header | 400 `invalid-precondition` |

Header values use strong comparison: quoted opaque tags, comma-separated
alternatives (including repeated header fields), or a lone `*`. A list agrees
with the body when it includes the body's quoted version. Valid opaque tags
that do not match are stale, not malformed. A wildcard accepts an existing
resource and resolves to its current version; it does not discard a separately
supplied body version. Missing or foreign-tenant resources return 404 without
revealing a version. Authentication and route permissions remain mandatory.

`app/api/conditional_requests.py` parses HTTP syntax and translates application
errors through the existing RFC 9457 handler. The framework-free
`app/shared/concurrency.py` resolves the precondition in each application
handler. Domain models stay unaware of HTTP. Repositories still compare the
resolved version atomically; a race after the initial read returns 412 for a
header client and 409 for a legacy client. Routers roll back before reading the
current version so an unsuccessful offer decision cannot persist partial work.
All new error identifiers are documented in `docs/api-errors.md` and headers and
status codes are described in OpenAPI. CORS permits `If-Match` and exposes ETag.

## Interaction with ADR-005

The candidate stage PATCH now uses the same optional `Idempotency-Key` guard as
POST commands. For both conditional commands, the raw `If-Match` header fields
are part of the fingerprint, including absence, field order and whitespace. A
successful replay is resolved before parsing or comparing a precondition, so a
retry returns the original 2xx body and original ETag after the aggregate has
advanced. Reusing that key with a different header returns 422. Other commands
retain their existing fingerprints and ignore `If-Match`.

ETag joins the stored response-header allowlist. Requests without the header
retain the original fingerprint format, so historical body-version approval
keys remain replayable. New keys have the usual ADR-005 guarantees and failure
window. Historical responses stored before this feature do not acquire an ETag
on replay.

## Verification and rollback

`tests/integration/test_conditional_requests.py` exercises both aggregates:
matching/stale/missing/contradictory conditions, wildcard and tag lists, malformed
headers, legacy 409 responses, replay before version comparison with stored
ETags, changed-key rejection, rollback on write conflict, tenant isolation, and
OpenAPI. Application tests verify no side effects on failed conditions.

No dependency, environment variable, schema migration or shared database write
is required. Rollback the API and web client together: the old API requires the
body version, so a client already sending only `If-Match` is not backward
compatible with it.
