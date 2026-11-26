# DUTH-108: List interviews and interviewers for the interview screens

## Context and problem

DUTH-54 (interview screens) is blocked because the API cannot list interviews or interviewers. Checked against `main` at `76661b0`:

- The only interview routes are `POST /v1/candidate-cases/{id}/interviews` and `POST /v1/interviews/{id}/feedback` (`app/api/interview_router.py`). Nothing lists interviews.
- Scheduling takes a raw `interviewer_id`. No endpoint lists the tenant members who can be scheduled, so a recruiter would have to paste a user id.
- The `interviewer` role has only `feedback:submit` (`app/modules/identity/security.py`). It cannot read candidates, so an interviewer cannot see which interviews they have or who the candidate is.

This spec covers the two read endpoints. Calendar self-service is DUTH-109.

## Goals

- An interviewer can see their own interviews, with enough context (candidate name, requisition title, feedback state) to give feedback.
- A recruiter or tenant admin can see every interview in the tenant, optionally for one interviewer.
- A recruiter can pick an interviewer from a list instead of typing an id.
- The web client gets the new contract through the regenerated `web/openapi.json` and `web/src/lib/api/schema.ts`.

## Non-goals

- Web UI (DUTH-54).
- Calendar subscription changes (DUTH-109).
- A display-name column on `users`. Both endpoints return email only.
- Granting the `interviewer` role `tenant:read`, or any other change to `ROLE_PERMISSIONS`.
- Filters other than `interviewer` (date range, upcoming only, candidate case). Ordering by `scheduled_at` lets the UI split past and upcoming itself.
- Returning feedback content in the list. `feedback_submitted` is a boolean.
- Changing which members can be scheduled. Scheduling keeps accepting only members with the `interviewer` role.

## Users and use cases

| Actor | Role(s) today | Use case |
|---|---|---|
| Interviewer | `interviewer` (`feedback:submit`) | "My interviews": see upcoming and past interviews, open one, submit feedback once. |
| Recruiter / tenant admin | `recruiter`, `tenant_admin` (`interview:manage`) | See all interviews in the tenant, or one interviewer's load. Pick an interviewer when scheduling. |
| Hiring manager / auditor | `tenant:read` only | No access to either endpoint (unchanged). |

## Contract

### `GET /v1/interviews`

Query parameters:

| Name | Type | Default | Rule |
|---|---|---|---|
| `interviewer` | `me` or a user id | omitted | See the authorization table below. |
| `cursor` | opaque string | none | Value of `next_cursor` from the previous page. |
| `limit` | integer 1–100 | 25 | Same bounds as `GET /v1/candidate-cases`. |

Response `200`, the same envelope as `GET /v1/candidate-cases`:

```json
{
  "items": [
    {
      "id": "…",
      "candidate_case_id": "…",
      "candidate_name": "Ada Lovelace",
      "requisition_title": "Backend Engineer",
      "interviewer_id": "…",
      "interviewer_email": "interviewer@example.com",
      "scheduled_at": "2026-12-01T09:00:00Z",
      "feedback_submitted": false
    }
  ],
  "next_cursor": "…",
  "total": 1
}
```

- `candidate_name` is `first_name + " " + last_name` of the candidate case. Anonymized cases show the redacted value the retention job wrote; nothing extra is hidden or added.
- A manager's `interviewer` value that matches no member of the tenant (unknown id, wrong format, any length) returns an empty page with `total: 0`, never `422` or `500`. For a caller without `interview:manage`, only the exact string `me` or their exact own id is accepted. Anything else (empty, `ME`, whitespace, another member's id, an unknown id) returns the same `403` body. The handler always filters a non-manager by `actor_id`, never by the parameter's value.
- `interviewer_email` is `users.email`, which is nullable, so the field is `string | null`.
- `feedback_submitted` is `true` when an `interview_feedback` row exists for the interview.
- `total` counts every interview that matches the filters, not just the page.
- Order: `scheduled_at` ascending, then `id` ascending. Pagination is keyset on `(scheduled_at, id)`, so the order stays stable while rows are added. The cursor is opaque to clients: unpadded URL-safe base64 of the JSON `{"s": "<scheduled_at ISO 8601 UTC>", "i": "<interview id>"}`. A cursor longer than 512 characters is rejected before decoding. Any cursor that fails to decode, is not a JSON object with string `s` and `i`, or has a timestamp without a UTC offset or one that cannot be parsed returns `422` problem+json with a generic `detail` that does not echo the payload. It never returns `500`. A cursor that decodes but was edited simply moves the keyset position; it cannot widen the tenant or ownership filters.

Authorization (`I` = caller holds `interview:manage`, `F` = caller holds `feedback:submit`):

| Caller | `interviewer` omitted | `interviewer=me` or own id | another user's id |
|---|---|---|---|
| `I` | all tenant interviews | own interviews | that user's interviews (empty list if they have none or are not a member) |
| `F` without `I` | own interviews | own interviews | `403` problem+json |
| neither | `403` problem+json | `403` problem+json | `403` problem+json |

"Own" means `interviews.interviewer_id == caller`. Every query is scoped to the caller's tenant on `interviews`, `candidate_cases` and `requisitions`.

### `GET /v1/interviewers`

- Requires `interview:manage`; otherwise `403` problem+json.
- Returns the caller's tenant members whose role grants `feedback:submit`, derived from `ROLE_PERMISSIONS` rather than a hard-coded role name. Today that is only `interviewer`, which matches who scheduling accepts.
- Response `200`: `{"items": [{"id": "…", "email": "…"}]}`, ordered by `email` (nulls last), then `id`. `email` is `string | null`.
- Both routes send `Cache-Control: private, no-store`, like the calendar feed.
- Not paginated: the list is bounded by tenant headcount and feeds a picker. The response is an object, so pagination fields can be added later without a breaking change.

## Acceptance criteria

- AC1: Given a tenant with interviews, when a caller with `interview:manage` calls `GET /v1/interviews`, then the response has `items`, `next_cursor` and `total`; each item has exactly `id, candidate_case_id, candidate_name, requisition_title, interviewer_id, interviewer_email, scheduled_at, feedback_submitted`; items are ordered by `scheduled_at`, then `id`.
- AC2: Given more interviews than `limit`, when the caller follows `next_cursor` until it is `null`, then every matching interview appears exactly once and `total` equals that count.
- AC3: Given two tenants with interviews, when a caller from tenant A lists interviews (with or without `interviewer`), then no interview, candidate name or requisition title from tenant B is returned, and `total` counts only tenant A rows. This also holds for a user who is an `interviewer` in both A and B with interviews in both: calling as A with `interviewer` omitted, `me` or their own id returns only A's interviews, without duplicates.
- AC4: Given a caller with `interview:manage`, when they pass `interviewer=<user_id>`, then only that interviewer's interviews are returned; `interviewer=me` returns only the caller's own.
- AC5: Given a caller with `feedback:submit` but not `interview:manage`, when they omit `interviewer`, pass `me` or pass their own id, then only interviews assigned to them are returned, including `candidate_name` and `requisition_title`.
- AC6: Given the same caller, when they pass another member's id, an unknown id, an empty value, `ME` or a value with whitespace, then the response is the same `403` problem+json body in every case and no data is returned.
- AC7: Given a caller with neither permission (`hiring_manager`, `auditor`), when they call `GET /v1/interviews` or `GET /v1/interviewers`, then the response is `403` problem+json.
- AC8: Given an interview with submitted feedback, when it is listed, then `feedback_submitted` is `true`; otherwise `false`.
- AC9: Given a malformed or tampered `cursor` (not base64, not JSON, a JSON array, missing keys, wrong types such as `{"s": null, "i": 1}`, a timestamp with no UTC offset, a bad timestamp, longer than 512 characters) or a `limit` outside 1–100, when the list is requested, then the response is `422` problem+json whose `detail` does not echo the cursor. Given a valid cursor issued in tenant B, when it is used in tenant A, then only tenant A rows are returned.
- AC9a: Given a manager, when they pass an `interviewer` value that is not a tenant member (including a 200-character string), then the response is `200` with `items: []` and `total: 0`.
- AC10: Given a tenant with interviewer, recruiter and admin members, and an interviewer in another tenant, when a caller with `interview:manage` calls `GET /v1/interviewers`, then only this tenant's `interviewer` members are returned as `id, email`, ordered by email. A user who is an `interviewer` in B and a `recruiter` in A is not returned in A.
- AC13: Given any successful response from either route, then it carries `Cache-Control: private, no-store`.
- AC11: `ROLE_PERMISSIONS` is unchanged; in particular `interviewer` still does not have `tenant:read`, and `GET /v1/candidate-cases` still returns `403` for an interviewer.
- AC12: `web/openapi.json` and `web/src/lib/api/schema.ts` are regenerated in the same PR, and `npm run api:check` in `web/` passes.

## Constraints

- Hexagonal boundaries: the list query lives in `app/modules/interviews/application` behind a port, the SQL in `app/modules/interviews/infrastructure`, the route in `app/api/interview_router.py`. The joins to `candidates` and `organization` persistence use the existing allow-list entries in `tests/architecture/test_dependency_rule.py`; if a new cross-context import is needed it gets its own documented entry.
- The authorization rule (own vs any) is decided in the application layer from the caller's permissions, not in the route, so it is unit-testable without HTTP.
- No schema change is expected. If the planner finds the `(tenant_id, interviewer_id, scheduled_at)` access path needs an index, add it through an Alembic expand-only migration.
- Errors use the existing problem+json handling (`docs/api-errors.md`).
- Quality gates: `ruff format --check`, `ruff check`, `uv run python -m pytest` with coverage ≥ 85%, `npm run api:check`, web build.

## Risks

- **Data exposure to interviewers.** This is the first endpoint that shows candidate data to a role without `tenant:read`. A missing tenant or ownership predicate would leak candidates across interviewers or tenants. Mitigation: AC3, AC5, AC6 and AC9 tests, the threat model below, and a `security_review` pass by Hoàng-Security.
- **Reads are not audited.** The interviewer's new access to candidate names leaves no audit record, consistent with every existing `GET` route. Accepted for this issue; whether to audit candidate-data reads is a product/compliance decision for duthaho, tracked as a follow-up.
- **Membership enumeration.** A manager passing an arbitrary id gets an empty list rather than `404`. Managers can already list interviewers, so this reveals nothing new.
- **Role/permission drift.** `GET /v1/interviewers` follows `feedback:submit`, while scheduling checks `role == "interviewer"`. They match today. If another role gains `feedback:submit`, the picker would offer members that scheduling rejects. A test pins the current equality so the drift fails CI.
- **Count cost.** `total` runs a second count query per page, as the candidate list already does. Acceptable at showcase scale.

## Open questions

None. Interpretations taken from the issue text and the DUTH-54 thread:

- "Leaving out `interviewer` returns their own list" applies to callers with only `feedback:submit`; a manager who leaves it out gets every interview, because AC2 of the issue says managers list every interview "filtered or not".
- Ordering is by `scheduled_at` instead of the candidate list's `id`, because a list of meetings sorted by random UUID is not usable. The envelope (`items`, `next_cursor`, `total`) is the same.

## Rollout and rollback

- Additive: two new `GET` routes, no permission or schema change. Existing clients are unaffected.
- Rollback: revert the implementation PR. DUTH-54 would return to `blocked`.

## Plan

### Design summary

No schema, permission or service-boundary change: two additive read routes over existing tables, inside the `interviews` context. The contract above is the design; this is where each piece lives.

| Layer | File | Change |
|---|---|---|
| Application | `app/modules/interviews/application/list_interviews.py` (new) | `ListInterviewsQuery(tenant_id, actor_id, can_manage, interviewer, cursor, limit)` and handler. Resolves the effective filter: `me`/own id → caller; omitted → all if `can_manage` else caller; other id → that id if `can_manage` else raises `InterviewListForbiddenError`. Framework-free. |
| Application | `app/modules/interviews/application/list_interviewers.py` (new) | `ListInterviewersQuery(tenant_id, roles)` and handler; the route passes the roles from `ROLE_PERMISSIONS` that grant `feedback:submit`. |
| Application | `app/modules/interviews/application/ports.py` | `InterviewListItem`, `InterviewPage`, `InterviewerItem` dataclasses and an `InterviewReadModel` protocol (`list_page`, `list_interviewers`). Cursor encode/decode lives here as pure functions raising `InvalidCursorError`. |
| Infrastructure | `app/modules/interviews/infrastructure/sqlalchemy_read_model.py` (new) | One `SELECT` joining `interviews → candidate_cases → requisitions`, `LEFT JOIN users`, `EXISTS` on `interview_feedback`; `tenant_id` predicate on `interviews`, `candidate_cases` and `requisitions`; keyset `(scheduled_at, id) > (:s, :i)`; `limit + 1`; separate `count()` with the same filters minus the keyset. Uses the existing `interviews→candidates` and `interviews→organization` allow-list entries. |
| API | `app/api/interview_router.py`, `app/api/schemas.py` | `GET /v1/interviews` resolves the actor via `resolve_actor` and returns `403` unless the role has `interview:manage` or `feedback:submit`; maps `InterviewListForbiddenError` → `403`, `InvalidCursorError` → `422` via `problem_details`. `GET /v1/interviewers` uses `require("interview:manage")`. Response models `InterviewListItem`, `InterviewListResponse`, `InterviewerListResponse`. |
| Client | `web/openapi.json`, `web/src/lib/api/schema.ts` | `make api-client` (exports the schema and runs `npm run api:generate`). |
| Docs | `docs/architecture.md` interviews row, `docs/api-errors.md` if a new problem `type` is added, README pattern catalog "keyset pagination" row if absent. |

Index: `interviews` has single-column indexes on `tenant_id` and `interviewer_id`. At showcase volume that is enough; no migration in this issue. If the implementer's `EXPLAIN` shows a sort over the whole tenant, add `ix_interviews_tenant_scheduled (tenant_id, scheduled_at, id)` through an expand-only Alembic migration and say so in the PR.

### Test plan

Each acceptance criterion maps to at least one test. Integration tests reuse the `setup_interview_context` style from `tests/integration/test_interviewer_feedback.py`.

| AC | Test | Level |
|---|---|---|
| AC1 | fields exactly match the contract; order by `scheduled_at` then `id` with two interviews at the same time | integration `tests/integration/test_interview_list.py` |
| AC2 | 7 interviews, `limit=3`: three pages, no duplicates or gaps, `total == 7`, last `next_cursor` is `null` | integration |
| AC3 | two tenants with interviews; manager and interviewer of A, with and without `interviewer`, see only A; `total` counts only A. Shared user: interviewer in A and B, called as A with omitted/`me`/own id → only A, no duplicates (T1, T4) | integration |
| AC4 | manager with `interviewer=<id>` and `interviewer=me` | integration |
| AC5 | interviewer with omitted, `me`, own id; sees `candidate_name` and `requisition_title`; another interviewer's interviews absent | integration |
| AC6 | interviewer passing another member's id, an unknown id, empty, `ME`, ` me ` → identical `403` bodies (T3, T6) | integration + unit authorization table |
| AC7 | `hiring_manager` and `auditor` → `403` on both routes | integration |
| AC8 | after `POST …/feedback`, `feedback_submitted` flips to `true` | integration |
| AC9 | parametrized bad cursors (`!!!`, base64 of non-JSON, JSON array, missing `i`, `{"s": null, "i": 1}`, `{"s": [], "i": {}}`, naive timestamp, 513 chars) and `limit=0`/`101` → `422` with no echo; tenant-B cursor replayed in A → only A rows (T5) | integration + unit on cursor codec |
| AC9a | manager with unknown id and a 200-char id → `200`, empty | integration |
| AC10 | interviewer in tenant A and B, recruiter, admin: only A's interviewer returned, ordered by email, null email last; user who is `interviewer` in B and `recruiter` in A absent (T8) | integration `tests/integration/test_interviewer_list.py` |
| AC13 | both routes return `Cache-Control: private, no-store` (T9) | integration |
| AC11 | snapshot of `ROLE_PERMISSIONS["interviewer"] == {"feedback:submit"}`; interviewer `GET /v1/candidate-cases` → `403`; roles with `feedback:submit` equal the roles scheduling accepts | unit + integration |
| AC12 | `npm run api:check` in CI (`web` job) | CI |
| — | handler scope resolution: every row of the authorization table, plus non-manager with `""`, `ME`, ` me ` → forbidden and never "all", without HTTP | unit `tests/unit/modules/interviews/test_list_interviews.py` |
| — | architecture rule still green (`tests/architecture`) | existing |

Gates before hand-off: `ruff format --check`, `ruff check`, `uv run python -m pytest` (coverage ≥ 85%), `npm run api:check`, `npm run build` in `web/`.

### Threat model

By Hoàng-Security on DUTH-108 (against spec head `aaa5e0d`).

Assets: candidate name and requisition title (candidate PII and hiring intent), member emails (staff PII), and the interview schedule. Trust boundary: everything from the caller is untrusted except the actor that `resolve_actor` derives from the JWT and the `memberships` row. That means `interviewer`, `cursor` and `limit` are untrusted. Production refuses development headers (`app/shared/settings.py`), so spoofing `X-Actor-Id` is out of scope.

| # | STRIDE | Threat | Mitigation / coverage |
|---|---|---|---|
| T1 | I | Cross-tenant leak through a shared user (`users` is global), if the query filters on the interviewer but drops `interviews.tenant_id` | Tenant predicate on all three tables; AC3 shared-user case |
| T2 | I / E | Ownership bypass: the handler uses the supplied `interviewer` instead of `actor_id` | Non-manager always filtered by `actor_id`; AC5, AC6, unit authorization table |
| T3 | E | Scope widening: empty, `ME` or whitespace makes a non-manager fall into "omitted → all" | Exact `me`/own id only, else `403`; AC6, unit table |
| T4 | I | Join fan-out or leak through untenanted joins (`memberships`, `candidate_cases`, `requisitions`) | No `memberships` join in the list; tenant predicate on each table; AC2, AC3 |
| T5 | T / D | Cursor tampering: injection, `500` on wrong types or naive timestamps, oversized input; cross-tenant replay | Bound parameters, 512-char cap, strict decode, `422`; replay only moves the keyset; AC9 |
| T6 | I | Enumeration through different `403`s for existing vs unknown ids | Identical `403` body; AC6. Managers get an empty list (AC9a), which reveals nothing they cannot list already |
| T7 | I | Over-exposure: ORM object or loose schema leaks candidate email, `created_by` or feedback | Explicit Pydantic `response_model`; AC1 "exactly" these fields |
| T8 | E | Role drift: the picker offers members scheduling rejects, or a recruiter in A who is an interviewer in B | Roles derived per tenant membership; AC10, AC11 equality pin |
| T9 | I | PII cached by shared proxies, or echoed in error `detail` | `Cache-Control: private, no-store` (AC13); generic `422` detail (AC9) |
| T10 | R | Interviewer reads of candidate names are not audited | Accepted for this issue, as for all `GET` routes; follow-up decision for duthaho |
| T11 | D | Expensive queries through large pages or per-page count | `limit` ≤ 100, global rate limiter (`app/shared/rate_limit.py`), count cost accepted in Risks |
| T12 | I | Stale access after offboarding or role change | `resolve_actor` reads `memberships` on every request; AC7 |

`security_review` on the implementation PR is required. Hoàng-Security will check the tenant predicates and joins (T1, T4), that non-managers are forced to `actor_id`, the cursor codec bounds, response headers and response model, and the `ruff`/`pytest` gates.

### Sub-issues by stage

None. The change is one cohesive API slice that cannot be verified in parts, so it ships as one PR on DUTH-108 itself.

| Stage | Work | Handler | ACs | Depends on |
|---|---|---|---|---|
| 1 | Implement both routes, tests, regenerated client, docs; PR titled `DUTH-108: Add interview and interviewer listing` | Quốc-BE | AC1–AC13 | this spec merged or approved |
| review | `code_review` → `security_review` (required: new candidate-data exposure to `interviewer`) → `qa` → `in_review` | Trung-PM, Hoàng-Security, Diễm-QA | — | stage 1 PR |

Follow-up outside this issue (needs a decision from duthaho, not blocking): audit candidate-data reads by the `interviewer` role, or record that reads are not audited (T10).

Downstream: DUTH-54 stays `blocked` until this PR and DUTH-109 merge; Hiếu-FE rebases onto `main` then.
