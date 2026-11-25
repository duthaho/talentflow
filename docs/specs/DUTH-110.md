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
- The response model is the same shape the `PUT` already returns, with `retention_days` made nullable for the `GET`. The `PUT` contract does not change.

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
- AC6: Given a case with an uploaded and downloaded attachment, when its timeline is read, then the `candidate_attachment.uploaded` and `candidate_attachment.downloaded` events appear; events for another case's attachment and events of other aggregate types (interview, requisition, tenant) do not.
- AC7: Given an audit row whose stored metadata contains `first_name`, `last_name`, `email`, `original_filename`, `sha256` or `reason` (seeded directly in the test), when the timeline is read, then none of those keys or their values appear in the response, and only the allowlisted keys for that action remain. An action missing from the allowlist returns `metadata: {}`.
- AC8: Given a malformed `cursor` or a `limit` outside 1–100, when the timeline is requested, then the response is `422` problem+json.
- AC9: Given no legal hold, when `GET …/legal-hold` is called, then the response is `200` with `held: false` and `null` for the other fields. After `PUT` with `held: true` it returns the reason, placement time and the placing user's id; after `PUT` with `held: false` it returns `held: false` again.
- AC10: Given no retention policy, when `GET /v1/retention-policy` is called, then the response is `200` with `retention_days: null`; after `PUT` with 90 it returns 90. Tenant B's policy is never returned to tenant A.
- AC11: Given the app is created with `attachment_max_bytes` overridden, when `GET /v1/attachment-policy` is called, then it returns that value and the sorted `ALLOWED_CONTENT_TYPES`.
- AC12: `GET /v1/audit-events` behaves exactly as before; its existing tests pass unchanged.
- AC13: `web/openapi.json` and `web/src/lib/api/schema.ts` are regenerated in the same PR with `make api-client`, and `npm run api:check` in `web/` passes.
- AC14: `ruff format --check`, `ruff check`, `uv run python -m pytest` (coverage ≥ 85%) and the web build pass; actual output is in the PR.

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
- **Cross-tenant or cross-case leak in the timeline.** The attachment join must carry the tenant predicate on both tables. Mitigation: AC2, AC6, AC10 tests with two tenants.
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

(added at the `plan` step)
