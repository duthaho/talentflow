# DUTH-110: Read APIs for candidate detail

## Context and problem

DUTH-53 (candidate detail page) is blocked because the API has no read endpoints for one candidate case and the data around it. Checked against `main` at `76661b0`:

- `GET /v1/candidate-cases` lists cases with filters and a cursor, but nothing returns a single case by id (`app/api/candidate_router.py`).
- `GET /v1/audit-events` returns every event in the tenant, unpaginated, with no filter and no timestamp (`app/api/audit_router.py`). It cannot drive a per-case timeline.
- Legal hold and retention policy have only `PUT` routes (`app/api/retention_router.py`). The UI cannot show the current state.
- The attachment size limit (`Settings.attachment_max_bytes`) and allowed content types (`ALLOWED_CONTENT_TYPES` in `app/modules/attachments/application/attachment_service.py`) exist only on the server. The web app would have to copy them.

Hiếu-FE is building DUTH-53 against typed mocks of the contract below, so this spec keeps the shapes from the issue. Any change to a shape is first raised on DUTH-53.

## Goals

- The candidate detail page can load the case, its audit timeline, its legal hold status, the tenant retention policy and the attachment upload rules from the API.
- The timeline is paginated, ordered newest first, and stays stable while new events are written.
- The timeline never shows candidate PII, even when the stored audit metadata contains it.
- The web client gets the contract through the regenerated `web/openapi.json` and `web/src/lib/api/schema.ts`.

## Non-goals

- Wiring the endpoints into the web pages (DUTH-53).
- Any change to `GET /v1/audit-events`.
- Any change to the existing `PUT` routes, the `POST`/`PATCH` candidate responses, or `ROLE_PERMISSIONS`.
- Interview, offer, calendar or requisition events in the case timeline. Only events on the case and its attachments are in scope; other aggregates can join the timeline in a later issue.
- Changing what the write paths store in `audit_events.metadata_json`. The allowlist filters on read.
- Keeping attachment events in the timeline after retention purge deletes the attachment rows (see Risks).

## Users and use cases

| Actor | Role(s) today | Use case |
|---|---|---|
| Recruiter / tenant admin | `recruiter`, `tenant_admin` | Open a candidate, see its details, history, legal hold and retention rules; upload a file that the client pre-validates. |
| Auditor | `auditor` (`audit:read`, `tenant:read`) | Read the case and its timeline. No legal hold or retention policy (needs `retention:manage`). |
| Hiring manager | `hiring_manager` (`tenant:read`) | Read the case and the attachment policy. Timeline, legal hold and retention policy return `403`; the page hides those panels. |

Which roles have which permission is read from `app/modules/identity/security.py`; this issue does not change it.

## Contract

All five routes are tenant-scoped through the existing `require(<permission>)` dependency. The permission check runs before the case lookup, so a caller without the permission gets `403` for any id. Errors use the existing problem+json types in `docs/api-errors.md` (`forbidden`, `not-found`, `validation-error`). Timestamps are ISO 8601 with a UTC offset.

### 1. `GET /v1/candidate-cases/{id}` — `tenant:read`

```json
{
  "id": "…",
  "requisition_id": "…",
  "first_name": "Ada",
  "last_name": "Lovelace",
  "email": "ada@example.com",
  "stage": "screening",
  "version": 3,
  "created_at": "2026-11-20T09:00:00Z"
}
```

- `404` (`not-found`) when the id does not exist or belongs to another tenant. Both cases return the same body.
- An anonymized case returns `200` with the redacted values the retention job wrote. Nothing is hidden or added.
- New response model (e.g. `CandidateCaseDetailResponse`); the existing `CandidateCaseResponse` stays as it is.

### 2. `GET /v1/candidate-cases/{id}/audit-events` — `audit:read`

Query parameters:

| Name | Type | Default | Rule |
|---|---|---|---|
| `cursor` | opaque string | none | `next_cursor` from the previous page. |
| `limit` | integer 1–100 | 25 | Same bounds as `GET /v1/candidate-cases`. |

```json
{
  "items": [
    {
      "id": "…",
      "action": "candidate_case.stage_transitioned",
      "aggregate_type": "candidate_case",
      "aggregate_id": "…",
      "actor_id": "…",
      "occurred_at": "2026-11-21T10:15:00Z",
      "metadata": {"from_stage": "applied", "to_stage": "screening", "version": 2}
    }
  ],
  "next_cursor": "…"
}
```

- Same `404` rule as (1), checked before any events are read.
- **Scope**: events in the caller's tenant where either
  - `aggregate_type = 'candidate_case'` and `aggregate_id = {id}`, or
  - `aggregate_type = 'candidate_attachment'` and `aggregate_id` is the id of a row in `candidate_attachments` with `candidate_case_id = {id}` and the same tenant.

  The join goes through `candidate_attachments.candidate_case_id`. The query never reads `metadata_json` to decide scope.
- **Order**: `created_at` descending, then `id` descending. `occurred_at` is `audit_events.created_at`; no new column.
- **Cursor**: keyset on `(created_at, id)`. The next page holds rows strictly older than the last row of the current page in that order. The cursor is an opaque, URL-safe encoding of that pair; clients must not parse it. A cursor that does not decode, or decodes to an invalid timestamp, returns `422` (`validation-error`). `next_cursor` is `null` on the last page. There is no `total`: a timeline does not need one, and counting would cost a second scan.
- **Stability**: events written after page 1 was read are newer than every cursor, so following `next_cursor` neither repeats nor skips an event.
- **Metadata allowlist**: `metadata` is built from a per-action allowlist of keys. Keys not on the list are dropped. An action not on the list returns `{}`. The list lives in the audit application layer as data, so adding an action is a one-line change with a test.

  | Action | Keys returned |
  |---|---|
  | `candidate_case.created` | `requisition_id`, `stage` |
  | `candidate_case.stage_transitioned` | `from_stage`, `to_stage`, `version` |
  | `candidate_case.legal_hold_set` | none |
  | `candidate_case.legal_hold_released` | none |
  | `candidate_case.retention_purged` | none |
  | `candidate_attachment.uploaded` | `document_type`, `content_type`, `size_bytes` |
  | `candidate_attachment.downloaded` | none |
  | anything else | none |

  Names, email, file names and the legal hold reason are never returned. `sha256` is dropped too: a file hash can identify a specific resume across systems, and the page has no use for it. `candidate_case_id` is dropped because the caller already has it.

### 3. `GET /v1/candidate-cases/{id}/legal-hold` — `retention:manage`

```json
{"held": true, "reason": "Pending litigation", "placed_at": "2026-11-22T08:00:00Z", "placed_by": "…"}
```

- Mirrors the existing `PUT` on the same path. A `candidate_legal_holds` row means `held: true`; `reason`, `placed_at` and `placed_by` come from its `reason`, `created_at` and `created_by` (a user id).
- No row returns `200` with `{"held": false, "reason": null, "placed_at": null, "placed_by": null}`. Releasing a hold deletes the row, so a released hold reads the same as one never placed; the timeline keeps the history.
- Same `404` rule as (1). A hold row whose `tenant_id` differs from the caller's is treated as no row.

### 4. `GET /v1/retention-policy` — `retention:manage`

- `{"retention_days": 90}` from the caller's tenant `retention_policies` row, or `{"retention_days": null}` with `200` when no row exists.
- Uses a separate response model, `RetentionPolicyReadResponse` (`retention_days: int | None`). The `PUT` keeps `RetentionPolicyResponse` (`retention_days: int`), so its OpenAPI schema and generated type do not change.

### 5. `GET /v1/attachment-policy` — `tenant:read`

```json
{"max_bytes": 5242880, "allowed_content_types": ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]}
```

- `max_bytes` is the running app's `Settings.attachment_max_bytes` (`request.app.state.runtime_settings`), not the module default, so a configured override is reported.
- `allowed_content_types` is `ALLOWED_CONTENT_TYPES`, sorted so the response and the generated types are deterministic.
- The upload endpoint keeps enforcing both values; the client check is only for early feedback.

## Acceptance criteria

- AC1: Given a case in tenant A, when a caller in tenant A with `tenant:read` calls `GET /v1/candidate-cases/{id}`, then the response is `200` with exactly `id, requisition_id, first_name, last_name, email, stage, version, created_at`.
- AC2: Given an unknown id, or a case in tenant B, when a caller in tenant A calls any of routes 1–3 with the right permission, then the response is `404` problem+json with type `not-found`, and the two bodies differ only in `instance` and `correlation_id`.
- AC3: Given a caller without the route's permission (e.g. `hiring_manager` on routes 2–4), when they call it with any id, then the response is `403` problem+json with type `forbidden`.
- AC4: Given a case with more events than `limit`, when the caller follows `next_cursor` until it is `null`, then every in-scope event appears exactly once, in `(created_at, id)` descending order, including events that share the same `created_at`.
- AC5: Given page 1 was read and new events were written for the case, when the caller requests page 2 with page 1's cursor, then no event from page 1 repeats and no older event is skipped.
- AC6: Given a case with an uploaded and downloaded attachment, when its timeline is read, then the `candidate_attachment.uploaded` and `candidate_attachment.downloaded` events appear; events for another case's attachment and events of other aggregate types (interview, requisition, tenant) do not. Two-tenant variants: a tenant-B attachment row whose `candidate_case_id` equals tenant A's case id, with an audit event for it, and a tenant-A audit event whose `aggregate_id` is a tenant-B attachment id. Neither event appears in tenant A's timeline.
- AC7: Given an audit row whose stored metadata contains `first_name`, `last_name`, `email`, `original_filename`, `sha256` or `reason` (seeded directly in the test), when the timeline is read, then none of those keys or their values appear in the response, and only the allowlisted keys for that action remain. An action missing from the allowlist returns `metadata: {}`. An allowlisted key whose value is not a scalar (`str`, `int`, `float`, `bool`, `None`) is dropped.
- AC8: Given a malformed `cursor` or a `limit` outside 1–100, when the timeline is requested, then the response is `422` problem+json, never `500`. Malformed includes: not base64, non-UTF-8 bytes after decoding, JSON that is not an object, a missing or non-string `i`, a `t` that is not a string or is a naive timestamp, and a cursor longer than 256 characters (rejected before decoding).
- AC9: Given no legal hold, when `GET …/legal-hold` is called, then the response is `200` with `held: false` and `null` for the other fields. After `PUT` with `held: true` it returns the reason, placement time and the placing user's id; after `PUT` with `held: false` it returns `held: false` again.
- AC10: Given no retention policy, when `GET /v1/retention-policy` is called, then the response is `200` with `retention_days: null`; after `PUT` with 90 it returns 90. Tenant B's policy is never returned to tenant A.
- AC11: Given the app is created with `attachment_max_bytes` overridden, when `GET /v1/attachment-policy` is called, then it returns that value and the sorted `ALLOWED_CONTENT_TYPES`.
- AC12: `GET /v1/audit-events` behaves exactly as before; its existing tests pass unchanged.
- AC13: `web/openapi.json` and `web/src/lib/api/schema.ts` are regenerated in the same PR with `make api-client`, and `npm run api:check` in `web/` passes.
- AC14: `ruff format --check`, `ruff check`, `uv run python -m pytest` (coverage ≥ 85%) and the web build pass; actual output is in the PR.
- AC15: Given a `next_cursor` taken from case X's timeline, when it is sent for case Y, or by a caller in tenant B for a case of their own, then only Y's or B's own in-scope events are returned. The cursor carries no scope.
- AC16: Given any `200` response from routes 1–3, then it carries `Cache-Control: private, no-store`.

## Constraints

- Hexagonal boundaries (`tests/architecture`):
  - Route 1 is a query in `app/modules/candidates/application` behind the candidate repository port.
  - Route 2 is a query in `app/modules/audit/application` behind a reader port. The case-existence check and the attachment join live in the audit infrastructure adapter. If that needs a new cross-context import (audit → candidates/attachments persistence), it gets its own documented entry in the dependency rule test; it does not go through the application layer.
  - The metadata allowlist and cursor encoding are plain Python in the audit application layer, unit-tested without a database.
  - Routes 3 and 4 are reads on `RetentionService` (or a read handler next to it) behind the retention repository port.
  - Route 5 reads settings and a constant in the route; no new module.
- **Index**: the timeline query filters on `(tenant_id, aggregate_type, aggregate_id)` and orders by `(created_at, id)`. Today `audit_events` has only `ix_audit_events_tenant_id`. Add a composite index on `(tenant_id, aggregate_type, aggregate_id, created_at, id)` through an Alembic **expand-only** migration (create index only, no column or data change; `downgrade` drops it). `candidate_attachments.candidate_case_id` is already indexed.
- **Timezones**: tests run on SQLite, which returns naive datetimes from `DateTime(timezone=True)`. The cursor encodes and compares in UTC, and `occurred_at` / `created_at` / `placed_at` are serialized with a UTC offset on both SQLite and PostgreSQL.
- Keyset comparison is written as `created_at < :ts OR (created_at = :ts AND id < :id)`, not a row-value comparison, so it runs the same on SQLite and PostgreSQL.
- Errors go through the existing problem+json handling; no new problem types.
- No new environment variables or secrets.

## Risks

- **PII leak through metadata.** Future write paths may add keys like a file name to an event. Mitigation: allowlist on read with default-deny, AC7 seeds PII keys directly, and a `security_review` pass by Hoàng-Security.
- **Cross-tenant or cross-case leak in the timeline.** The attachment join must carry the tenant predicate on both tables. Mitigation: AC2, AC6 (two-tenant variants), AC10 and AC15.
- **Case enumeration.** Unknown and foreign ids return the same `404`, so ids cannot be probed across tenants.
- **Attachment events disappear after retention purge.** Purge deletes `candidate_attachments` rows, so the join no longer finds their events; the `candidate_case.retention_purged` event stays. This is accepted for now: the purged case keeps a visible purge marker and the full history remains in `GET /v1/audit-events`. Keeping them would need the attachment id stored on the case side or soft-deleted attachments, which is a separate decision.
- **Index build on a large table.** A plain `CREATE INDEX` locks writes to `audit_events` while it builds. At showcase data volume this is negligible; the migration docstring notes that production would use `CREATE INDEX CONCURRENTLY`.
- **Contract drift with DUTH-53 mocks.** Shapes here match the issue text. Any change goes to DUTH-53 first.

## Open questions

None. The decisions above that go beyond the issue text (`sha256` dropped from metadata, no `total` on the timeline, attachment events lost after purge, interview events out of scope) stay inside the issue's contract and are recorded here for review.

## Rollout and rollback

- Purely additive: five new `GET` routes, one expand-only index migration, regenerated client types. No existing route, response or permission changes.
- Ship in one PR. After merge, DUTH-53 swaps its mocks for the generated client types.
- Rollback: revert the PR and run the migration's `downgrade` (drops the index). No data is written or transformed, so nothing needs repair.

## Plan

### Design summary

Five additive read routes over existing tables plus one expand-only index. No permission, column or public write-contract change. The contract above is the design; this table says where each piece lives.

| Layer | File | Change |
|---|---|---|
| Candidates | `app/modules/candidates/application/get_candidate.py` (new), `ports.py` | `GetCandidateHandler(tenant_id, candidate_case_id)` returns a `CandidateDetail` view or raises `CandidateNotFoundError`. Repository gains `get_detail(tenant_id, id)`, filtering on both. |
| Audit, application | `app/modules/audit/application/case_timeline.py` (new) | `CaseTimelineQuery(tenant_id, candidate_case_id, cursor, limit)`, handler, `TimelinePage`, the `METADATA_ALLOWLIST` dict and `redact(action, metadata)`, and cursor `encode`/`decode` raising `InvalidCursorError`. The cursor is base64url JSON `{"t": <UTC ISO>, "i": <id>}`. Framework-free. |
| Audit, infrastructure | `app/modules/audit/infrastructure/sqlalchemy_reader.py` | `case_exists(tenant_id, id)` and `list_for_case(tenant_id, id, after, limit)`. One `SELECT` on `audit_events` with `tenant_id = :t AND ((aggregate_type='candidate_case' AND aggregate_id=:id) OR (aggregate_type='candidate_attachment' AND aggregate_id IN (SELECT id FROM candidate_attachments WHERE candidate_case_id=:id AND tenant_id=:t)))`, the keyset predicate from Constraints, `ORDER BY created_at DESC, id DESC`, `LIMIT limit+1`. |
| Architecture rule | `tests/architecture/test_dependency_rule.py` | Two new documented entries: `("audit", "candidates")` "case timeline checks the case exists in the tenant" and `("audit", "attachments")` "case timeline joins attachment ids". This is the same read-side pattern `retention` already uses. |
| Retention | `app/modules/retention/application/retention.py`, repository | `get_legal_hold(tenant_id, id)` returns a `LegalHoldView` (raises `CandidateNotFoundError` for unknown or foreign cases) and `get_policy(tenant_id)` returns `int \| None`. Reuses `candidate_exists`. |
| Migration | `migrations/versions/<rev>_index_audit_events_by_aggregate.py` (new) | `create_index("ix_audit_events_tenant_aggregate_created", "audit_events", ["tenant_id", "aggregate_type", "aggregate_id", "created_at", "id"])`; `downgrade` drops it. The model's `__table_args__` declares the same index so autogenerate stays clean. |
| API | `app/api/candidate_router.py`, `audit_router.py`, `retention_router.py`, `attachment_router.py` (or a small `policy` route next to it), `schemas.py` | Routes 1–5 with `require(...)`. `CandidateNotFoundError` → `404`, `InvalidCursorError` → `422`, through the existing problem+json handling. New models: `CandidateCaseDetailResponse`, `CaseAuditEventItem`, `CaseAuditEventPage`, `LegalHoldResponse`, `RetentionPolicyReadResponse`, `AttachmentPolicyResponse`. |
| Client | `web/openapi.json`, `web/src/lib/api/schema.ts` | `make api-client`. |
| Docs | `docs/architecture.md` (audit context read side), README pattern catalog | Add a "PII allowlist on audit read" row pointing at `case_timeline.py` and its tests. Check the keyset pagination row exists. |

Route order: `GET /v1/candidate-cases/{id}` is registered after the static `GET /v1/candidate-cases`; no static sub-path collides with `{id}`.

### Test plan

| AC | Test | Level |
|---|---|---|
| AC1 | exact field set; `created_at` carries a UTC offset | integration `tests/integration/test_candidate_detail_read.py` |
| AC2 | unknown id and tenant-B id on routes 1–3: both `404`, `type` `not-found`, bodies equal except `instance`/`correlation_id` | integration, parametrized over routes |
| AC3 | `hiring_manager` on routes 2–4 and `auditor` on 3–4 → `403` `forbidden`, with both a real and an unknown id | integration, parametrized |
| AC4 | 7 events, 3 with the same `created_at` (set explicitly); `limit=3` walk: no duplicates or gaps, strict `(created_at, id)` desc order, last `next_cursor` `null` | integration `tests/integration/test_case_timeline.py` |
| AC5 | read page 1, transition the stage twice, read page 2 with the old cursor: no overlap, nothing skipped | integration |
| AC6 | upload + download on case X, upload on case Y, schedule an interview on X: X's timeline has its two attachment events, none from Y, no `interview.*`. Two-tenant variants: a tenant-B attachment pointing at A's case id, and a tenant-A event naming a tenant-B attachment id; neither appears | integration |
| AC7 | seed `audit_events` rows directly with `first_name`, `last_name`, `email`, `original_filename`, `sha256`, `reason`, `candidate_case_id` and an unknown action; assert no forbidden key **or value** appears anywhere in the serialized response; unknown action → `{}`; a nested dict under `stage` is dropped | integration + unit on `redact` for every allowlist row |
| AC8 | bad cursors (`!!!`, non-UTF-8 after base64, JSON array, missing or non-string `i`, list or naive `t`, 257 characters) and `limit=0`/`101` → `422` problem+json; the codec unit test asserts only `InvalidCursorError` escapes | integration + unit on the cursor codec |
| AC9 | hold lifecycle: none → set → read → release → read | integration `tests/integration/test_candidate_retention.py` (extend) |
| AC10 | none → `null`; `PUT 90` → `90`; tenant B policy invisible to A; PUT schema unchanged (`retention_days` still required in `openapi.json`) | integration |
| AC11 | `create_app(..., app_settings=Settings(attachment_max_bytes=1234))` → `1234` and sorted types | integration |
| AC12 | existing `GET /v1/audit-events` tests untouched and green | existing |
| AC13 | `npm run api:check` (CI `web` job and locally) | CI |
| AC14 | gates below | local + CI |
| AC15 | cursor from X's page 1 sent for Y, and by a tenant-B caller for B's case: results equal Y's or B's own scoped rows | integration |
| AC16 | header asserted on routes 1–3 | integration |
| — | migration `upgrade`/`downgrade` round-trip on PostgreSQL, if the repo has a migration test harness; otherwise `alembic upgrade head` against the compose Postgres, with output in the PR | manual/CI |
| — | architecture rule green with the two new entries | existing |

Gates before hand-off: `ruff format --check`, `ruff check`, `uv run python -m pytest` (coverage ≥ 85%), `npm run api:check` and `npm run build` in `web/`.

### Threat model

From Hoàng-Security on DUTH-110, against spec `1a7b8b8`. Route 2 is the first API route that returns audit metadata, so the default-deny allowlist is the main control. Today's write paths store no names, email or file names; the allowlist protects against paths added later.

| # | STRIDE | Threat | Control | Covered by |
|---|---|---|---|---|
| T1 | I | Reading another tenant's case, timeline or hold by id | Every lookup is `WHERE id = :id AND tenant_id = :t` | AC2 |
| T2 | I | Probing which ids exist in other tenants | Same 404 body from one query | AC2 |
| T3 | I | Cross-case or cross-tenant leak through the attachment join | Tenant predicate on both `audit_events` and `candidate_attachments`; scope never read from `metadata_json` | AC6 (two-tenant variants) |
| T4 | I | PII in stored metadata | Per-action key allowlist, default-deny, scalar values only | AC7, unit tests on `redact` |
| T5 | T/I | Forged cursor reaches out-of-scope events | Cursor is only a keyset bound on top of the scope predicate, so no signature is needed | AC15 |
| T6 | T | SQL injection through cursor or `limit` | Typed decode, bound parameters, no interpolated `text()` | AC8, security review |
| T7 | D/I | Malformed or huge cursor causes a 500 or burns CPU | All decode errors → `InvalidCursorError` → 422; length cap before decoding | AC8 |
| T8 | D | Expensive timeline scans | `limit` 1–100, composite index, no `COUNT`, global rate limit | AC8, index migration |
| T9 | E | Role reads more than allowed | `require()` before lookup; `ROLE_PERMISSIONS` unchanged | AC3 |
| T10 | I | Free-text hold `reason` leaks | Only on route 3 (`retention:manage`); never in timeline metadata or logs | AC3, AC7 |
| T11 | I | Future ORM columns leak | Explicit response models | AC1 |
| T12 | I | Browser or proxy caches candidate PII | `Cache-Control: private, no-store`, as `calendar_router` does | AC16 |
| T13 | R | Reads of candidate PII are not audited | Accepted (Low): the existing list route is not audited either; separate follow-up if read auditing becomes a goal | — |
| T14 | I | `actor_id` / `placed_by` may be an email-like OIDC `sub` | Accepted (Low): staff identifiers, already in every audit row | — |

`security_review` on the implementation PR stays required. It checks the allowlist against this spec row by row, the two-table tenant predicate, cursor decode error paths, bound parameters, no `reason` or metadata in logs or spans, and the new read-only dependency entries, plus `pip-audit` and a secret scan. A gap in AC6, AC8, AC15, T3 or T4 is a blocking High.

### Sub-issues by stage

None. The five routes are one API slice for one page, with one PR to review and verify, so the work ships as one PR on DUTH-110 itself.

| Stage | Work | Handler | ACs | Depends on |
|---|---|---|---|---|
| 1 | Implement routes 1–5, migration, tests, regenerated client and docs. PR titled `DUTH-110: Add candidate detail read APIs`, linking this spec | Quốc-BE | AC1–AC16 | spec PR #15 approved; requester approves this plan |
| review | `code_review` → `security_review` (required: PII allowlist, cross-tenant join) → `qa` → `in_review` | Trung-PM, Hoàng-Security, Diễm-QA | — | stage 1 PR |

Downstream: DUTH-53 stays `blocked` until this PR merges. Hiếu-FE then replaces the mocks with the generated types.
