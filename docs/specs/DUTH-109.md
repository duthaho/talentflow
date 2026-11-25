# DUTH-109: Let interviewers create, list and revoke their own calendar links

## Context and problem

DUTH-54 AC2 says interviewers generate or revoke their own calendar subscription link in the web app. The API does not allow that today:

- `POST /v1/calendar-subscriptions` and `DELETE /v1/calendar-subscriptions/{id}` both need `calendar:manage` (`app/api/calendar_router.py`). Only `tenant_admin` and `recruiter` have it (`app/modules/identity/security.py`). The `interviewer` role has only `feedback:submit`.
- Create accepts any `interviewer_id` in the tenant, and revoke works on any subscription in the tenant. Giving interviewers `calendar:manage` would let any interviewer mint a feed for a colleague and read their interview schedule, so that is not an option.
- Nothing lists subscriptions. After a page reload the UI cannot know a link exists, so it cannot show a Revoke button.

## Goals

- An interviewer can create, list and revoke their own calendar links, and nobody else's.
- The UI can show which links the interviewer has without ever seeing a feed token again.
- Recruiters and tenant admins (`calendar:manage`) keep today's behavior and can also list links for an interviewer.
- The role/permission model is written down in a matrix in the docs, and a test keeps it equal to `ROLE_PERMISSIONS`.

## Non-goals

- Web UI. Hiếu-FE builds it in DUTH-54 on top of this API.
- Changing the feed endpoint `GET /v1/calendar-feeds/{token}.ics`, token format, hashing or lifetime.
- Limiting how many active links an interviewer may hold, or rotating a link in one call.
- Pagination of the list endpoint (an interviewer holds a handful of links at most).
- Sharing one permission source between the API and the web app. `web/src/lib/actor/actor.ts` and `web/test/role-permissions.ts` stay hand copies; generating them from the API is a possible follow-up.
- A general ownership/ABAC framework. This is one scoped permission, not a new authorization model.

## Users and use cases

- **Interviewer:** subscribes their calendar app to their interviews; later revokes the link when a device is lost or the link leaked.
- **Recruiter / tenant admin:** creates or revokes a link for an interviewer (as today) and can now see which active links an interviewer has.

## Acceptance criteria

Definitions: a subscription is **active** when `revoked_at` is null and `expires_at` is in the future. A **self-only caller** has `calendar:self` but not `calendar:manage`. All errors are RFC 9457 problem+json (`docs/api-errors.md`).

- AC1 (permission): `calendar:self` is added to `ROLE_PERMISSIONS["interviewer"]`. `tenant_admin` and `recruiter` are unchanged. `GET /v1/me` returns `calendar:self` for interviewers.
- AC2 (self-create): Given a self-only caller, when they `POST /v1/calendar-subscriptions` with no `interviewer_id` or with `interviewer_id` equal to their own id, then a subscription for the caller is created and the response is `201` with `id, interviewer_id, feed_url, expires_at`. The feed URL and token appear only in this response.
- AC3 (create for someone else is forbidden): Given a self-only caller, when they `POST` with any other `interviewer_id` (existing or not, same tenant or not), then the response is `403` problem+json and nothing is written or audited as created.
- AC4 (manage create unchanged): Given a caller with `calendar:manage`, when they `POST` with an `interviewer_id`, then today's behavior holds (`201`, or `404` when the id is not an interviewer in the tenant). When they leave `interviewer_id` out, the caller is used as the interviewer, so a recruiter who is not an interviewer gets `404 Interviewer not found`.
- AC5 (self-revoke): Given a self-only caller, when they `DELETE /v1/calendar-subscriptions/{id}` for one of their own non-revoked subscriptions, then it is revoked, the response is `204`, the audit trail records `calendar_subscription.revoked` with the caller as actor, and the feed URL returns `404` afterwards.
- AC6 (revoke someone else's is hidden): Given a self-only caller, when they `DELETE` a subscription that belongs to another interviewer in the same tenant, then the response is `404` problem+json with the same body as for a non-existent id, and the subscription stays active.
- AC7 (manage revoke unchanged): Given a caller with `calendar:manage`, when they `DELETE` any non-revoked subscription in their tenant, then it is revoked as today.
- AC8 (list own): Given a self-only caller, when they `GET /v1/calendar-subscriptions?interviewer=me`, then the response is `200` with their active subscriptions as `[{id, created_at, expires_at}]`, newest first. Revoked and expired subscriptions are left out. The same shape, filter and order apply when a `calendar:manage` caller lists by `<user_id>` (AC10).
- AC9 (list never leaks secrets): The list response schema has no `feed_url`, `token` or `token_hash` field, and a test asserts that the token returned at create time does not appear anywhere in the list response body.
- AC10 (list scope): `interviewer` takes `me` or a user id of 1–128 characters, the same bounds as `interviewer_id`; a missing, empty or longer value returns `422` before any query runs. Given a self-only caller, when `interviewer` is any value other than `me` or their own id, then the response is `403`. Given a caller with `calendar:manage`, `interviewer` may be `me` or any user id; an id with no subscriptions in the tenant returns `200 []`. A caller with neither permission gets `403` on all three endpoints.
- AC11 (tenant isolation): Given subscriptions and interviewers in tenant A, when a caller in tenant B uses tenant A's ids, then the response never contains tenant A's data and tenant A's subscriptions stay active. Expected status per caller:
  - self-only caller: create with a tenant-A `interviewer_id` → `403` (AC3); list with a tenant-A user id → `403` (AC10); revoke a tenant-A subscription id → `404` (AC6).
  - `calendar:manage` caller: create with a tenant-A `interviewer_id` → `404` (AC4); list with a tenant-A user id → `200 []`; revoke a tenant-A subscription id → `404`.
- AC12 (contract and docs): The OpenAPI schema and `web/src/lib/api/schema.ts` are regenerated; `calendar:self` is added to the web app's known permissions (`web/src/lib/actor/actor.ts`, `web/test/role-permissions.ts`) so it is not dropped. A role/permission matrix table is added to `docs/architecture.md` (identity section) with a short note on why `calendar:self` is scoped to the caller, and a pytest parses that table and asserts it equals `ROLE_PERMISSIONS`, so the doc fails CI when it drifts. The web allowlists stay hand-maintained in this issue (see Non-goals).
- AC13 (quality gates): `ruff format --check`, `ruff check`, `uv run python -m pytest` with coverage ≥ 85%, the architecture tests, and the web typecheck/build pass.

## Constraints

- The ownership decision lives in the application layer (`CalendarSubscriptionService`), not only in the router, so it is unit-testable and stays framework-free (`tests/architecture`). The router resolves the caller's effective scope (`manage` or `self`) and passes it in.
- `require()` checks one permission today. The endpoints need "either `calendar:manage` or `calendar:self`"; that must not loosen any other route.
- Self-revoke checks ownership in the same query that loads the subscription (`tenant_id`, `id` and `interviewer_id`), so a foreign subscription is indistinguishable from a missing one (AC6).
- No schema migration is expected: the list reads existing columns. If an index on `(tenant_id, interviewer_id)` is needed it ships through Alembic as an additive change.
- `POST` request body: `interviewer_id` becomes optional. This is backward compatible for existing callers.
- RBAC change: the issue goes `code_review → security_review` (Hoàng-Security) before `qa` and `in_review`.

## Risks

- **Privilege escalation through the new permission.** A mistake in the self check would let an interviewer read a colleague's schedule. Mitigated by AC3, AC6, AC10 and AC11 tests and the security review.
- **Existence oracle.** Returning `403` for a foreign subscription on revoke would confirm it exists; AC6 requires `404`. Create returns `403` instead because the only id a self-only caller may name is their own, so there is nothing to hide.
- **Link sprawl.** Without a cap, an interviewer can create many active links; each is a bearer credential. Accepted for now (links expire after `CALENDAR_SUBSCRIPTION_LIFETIME_DAYS`); the list makes them visible and revocable. A cap can follow if security review asks for one.
- **Web permission drift.** If `calendar:self` is missing from the web allowlist, the UI silently hides the feature. Covered by AC12.

## Open questions

None blocking. Decisions taken in this spec, open for spec review to challenge:

- Omitted `interviewer_id` on create means "the caller" for every caller, not only self-only callers (AC4).
- `interviewer=me` and the caller's own id are equivalent for self-only callers (AC10).
- List returns active links only; there is no history view (AC8).
- The permission matrix lives in `docs/architecture.md` next to the identity section and is checked against `ROLE_PERMISSIONS` by a pytest (AC12); it is hand-written, not generated.

## Rollout and rollback

- Rollout: single PR, no migration and no new env vars. Interviewers gain `calendar:self` on deploy; the UI in DUTH-54 starts using it after merge.
- Rollback: revert the PR. Links created by interviewers stay valid until they expire or a recruiter revokes them, which is the same state a recruiter-created link would be in.

## Plan

Inputs: technical design by Đông-SA and threat model by Hoàng-Security, both on DUTH-109 against spec head `e41493c`. Neither changes an acceptance criterion; two small additions are folded in below (D6, I6).

### Design summary

- D1 **Scope from the server.** `security.py` gains `require_any(*permissions)` and `permissions_for(role)`; `require()` and `ActorContext` are unchanged. The router computes `CalendarScope.MANAGE` when the role has `calendar:manage`, else `CalendarScope.SELF` (`manage` wins). Nothing in the request can choose the scope.
- D2 **Ownership in the application layer.** `CalendarSubscriptionService.create/revoke/list_active` take a required `scope` keyword (no default; unknown or `None` raises). In self scope the requested id is compared to `actor_id` with exact `==`, and a mismatch raises `CalendarSubscriptionForbiddenError` before any repository call. Every write and query then uses `actor_id`, never the requested value. The router maps Forbidden → 403 and NotFound → 404 with static `detail` strings that never echo an id.
- D3 **Repository port.** `get_owned(subscription_id, tenant_id, interviewer_id | None)` is one `SELECT` filtered by `id`, `tenant_id`, `revoked_at IS NULL` and, in self scope, `interviewer_id`. New `list_active(tenant_id, interviewer_id, now)` orders by `created_at DESC, id DESC`. Both always filter on `tenant_id` from `ActorContext`.
- D4 **No migration.** `tenant_id` and `interviewer_id` are already indexed; a composite index waits for real volume and would ship as an additive Alembic revision.
- D5 **Schemas.** `CreateCalendarSubscriptionRequest.interviewer_id: str | None` (1–128 chars; omitted or `null` means the caller). New `CalendarSubscriptionSummary {id, created_at, expires_at}` with `extra="forbid"`, built field by field; `GET` returns a bare array. Query `interviewer`: required, 1–128 chars, `me` is the only literal (case-sensitive).
- D6 **Headers and audit.** `Cache-Control: private, no-store` on the `201` create response and on the list response. Audit metadata for `created`/`revoked` gains `"scope"`; it never contains `token`, `token_hash` or `feed_url`.
- D7 **Permission matrix.** Table in `docs/architecture.md` §8 between `<!-- permission-matrix:start -->` and `<!-- permission-matrix:end -->`, permissions as rows, roles as columns, `✓` or empty. `tests/unit/test_permission_matrix.py` (stdlib only) parses it and asserts it equals `ROLE_PERMISSIONS`; unknown cell values, duplicate rows and missing markers fail.

### Threat model

Verdict from Hoàng-Security: sound, nothing Critical or High provided these invariants hold. They are the `security_review` checklist.

- I1 Server-derived scope; fail closed on unknown scope.
- I2 In self scope the target is always `actor_id`; exact comparison, no normalisation.
- I3 Authorize before existence: self-scope create and list return 403 before any repository call, so the self path cannot probe membership.
- I4 Ownership checked inside the single `get_owned` query, never by loading and comparing in Python.
- I5 Tenant from `ActorContext` only, on every query (covers one user with memberships in two tenants).
- I6 Secret-free outputs by allowlist: dedicated list model; audit keys are an exact expected set; `no-store` on create.

Accepted residual risks: `development_headers` auth trusts `X-Actor-Id` (already refused in production); no cap on active links per interviewer (links expire, are listed and revocable). Follow-up, filed separately on approval: soft cap on active links per interviewer, purge of expired rows via retention, and invalidating feed tokens when membership is removed (pre-existing).

### Test plan

Every AC maps to at least one integration test in `tests/integration/test_calendar_subscriptions.py` plus service unit tests with a fake repository.

| Spec AC | Tests |
|---|---|
| AC1 | `/v1/me` for an interviewer contains `calendar:self`; matrix test (AC12) |
| AC2 | self-create without and with own `interviewer_id` → 201, feed works |
| AC3 | A1: colleague id plus extra body field → 403, zero new rows and audit events; A2: case/whitespace variants and literal `"me"` → 403 or 422 |
| AC4 | manage create unchanged; recruiter omits `interviewer_id` → 404 |
| AC5 | self-revoke → 204, audit actor is caller with `scope=self`, feed → 404 |
| AC6 | A3: foreign, missing, already-revoked and tenant-B ids → byte-identical 404 bodies (ignoring `instance`); foreign link stays active, feed still 200, no audit event |
| AC7 | manage revoke of any tenant link → 204 |
| AC8 | list returns active only, newest first, exact keys; same for manage listing by `<user_id>` |
| AC9 | A6: token, `token_hash` and `feed_url` absent from list body, audit metadata and `GET /v1/audit-events` |
| AC10 | A4: self-list for colleague, tenant-B and unknown ids → 403 and no repository call (spy); 422 for missing/empty/129-char `interviewer`; A7: `hiring_manager` and `auditor` → 403 on all three endpoints, also with a malformed query (error-order pin) |
| AC11 | A5: same user in tenants A and B; A8: manage list of a tenant-B user → `200 []`, manage revoke of a tenant-B id → 404 |
| AC12 | matrix drift test; OpenAPI and `web/src/lib/api/schema.ts` regenerated; `calendar:self` in `actor.ts` and `role-permissions.ts`; web typecheck and tests |
| AC13 | `ruff format --check`, `ruff check`, `uv run python -m pytest` (coverage ≥ 85%), web build |
| Extra | A9: service raises on unknown/`None` scope and writes nothing; A10: interviewer still gets 403 on every other route needing a permission it lacks; A11: `201` has `Cache-Control: no-store` |

### Delivery

One PR, no sub-issues. The API, tests, regenerated OpenAPI/`schema.ts`, web allowlists and the doc matrix must land together for AC12 to hold, and splitting by layer is not allowed by the conventions.

- **Work item:** DUTH-109 itself, stage 1, handler Quốc-BE, branch `agent/quoc-be/DUTH-109-self-calendar-links`, PR titled `DUTH-109: Let interviewers manage their own calendar links`, linking this spec.
- **Acceptance:** spec AC1–AC13 plus D1–D7, I1–I6 and tests A1–A11 above.
- **Dependencies:** none upstream (spec merged or approved). Downstream: unblocks DUTH-54 AC2 (Hiếu-FE).
- **Review path:** `code_review` (Trung-PM) → `security_review` (Hoàng-Security, checks I1–I6) → `qa` (Diễm-QA) → `in_review` (duthaho).
- **Follow-up issue (backlog, not part of this delivery):** "Cap active calendar links and purge expired ones", handler Quốc-BE, from the threat model's Low findings.
