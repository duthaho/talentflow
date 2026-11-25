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
- The permission model is written down in a matrix that the docs and the web app share.

## Non-goals

- Web UI. Hiếu-FE builds it in DUTH-54 on top of this API.
- Changing the feed endpoint `GET /v1/calendar-feeds/{token}.ics`, token format, hashing or lifetime.
- Limiting how many active links an interviewer may hold, or rotating a link in one call.
- Pagination of the list endpoint (an interviewer holds a handful of links at most).
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
- AC8 (list own): Given a self-only caller, when they `GET /v1/calendar-subscriptions?interviewer=me`, then the response is `200` with their active subscriptions as `[{id, created_at, expires_at}]`, newest first. Revoked and expired subscriptions are left out.
- AC9 (list never leaks secrets): The list response schema has no `feed_url`, `token` or `token_hash` field, and a test asserts that the token returned at create time does not appear anywhere in the list response body.
- AC10 (list scope): Given a self-only caller, when `interviewer` is any value other than `me` or their own id, then the response is `403`. Given a caller with `calendar:manage`, `interviewer` may be `me` or any user id; an id with no subscriptions in the tenant returns `200 []`. A missing `interviewer` parameter returns `422`. A caller with neither permission gets `403` on all three endpoints.
- AC11 (tenant isolation): Given subscriptions in tenant A, when a caller in tenant B (any permission) lists, revokes or creates against those ids, then they see an empty list or `404`, never tenant A's data.
- AC12 (contract and docs): The OpenAPI schema and `web/src/lib/api/schema.ts` are regenerated; `calendar:self` is added to the web app's known permissions (`web/src/lib/actor/actor.ts`, `web/test/role-permissions.ts`) so it is not dropped. A role/permission matrix is added to the docs with a short note on why `calendar:self` is scoped to the caller.
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
- The permission matrix lives in `docs/architecture.md` next to the identity section, generated from or checked against `ROLE_PERMISSIONS` by a test so it cannot drift.

## Rollout and rollback

- Rollout: single PR, no migration and no new env vars. Interviewers gain `calendar:self` on deploy; the UI in DUTH-54 starts using it after merge.
- Rollback: revert the PR. Links created by interviewers stay valid until they expire or a recruiter revokes them, which is the same state a recruiter-created link would be in.

## Plan

(added at the `plan` step)
