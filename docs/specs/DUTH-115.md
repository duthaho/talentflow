# DUTH-115: Offer read APIs and decision reasons for the approval inbox

## Context and problem

DUTH-55 (offer approval inbox) cannot be built against the API. Checked against `main` at `84e1b7d`:

- `app/api/offer_router.py` has only `POST /v1/candidate-cases/{id}/offers` and `POST /v1/offers/{id}/approvals`. Nothing reads an offer, lists offers, or finds the offer for a case.
- `ApprovalDecision` (`app/modules/offers/infrastructure/models.py`) stores `offer_id, tenant_id, step, actor_id, decision`. It has no reason and no timestamp, so the UI cannot show "rejected by X on D because R".
- `ApproveOfferRequest` accepts only `decision` and `expected_version`.
- The approver is decided by `ApprovalPolicy.standard()`: step 1 `hiring_manager`, step 2 `tenant_admin`. `Offer.decide` rejects any other role. A member has exactly one role per tenant (`memberships.role`, `ActorContext.role`).

DUTH-55 AC2 asks for an inbox per approver, approve/reject with a reason, and the decision history. AC3 asks that actions the caller cannot take are hidden in the UI and rejected by the API.

## Goals

- An approver sees the offers waiting on their step, and nothing else, in one paginated call.
- Anyone who may read offers opens one offer and sees its decision history, oldest first, with reasons.
- A recruiter finds the offer for a candidate case.
- A rejection always carries a reason; an approval may.
- The web app knows whether the caller may decide an offer, without copying `ApprovalPolicy` into TypeScript.
- The web client gets the contract through the regenerated `web/openapi.json` and `web/src/lib/api/schema.ts`.

## Non-goals

- Wiring the endpoints into the web app (DUTH-55).
- Changing `ApprovalPolicy`, the steps, `ROLE_PERMISSIONS`, or who may decide.
- Candidate name or requisition title in offer responses. The inbox gets those from `GET /v1/candidate-cases/{id}` (DUTH-110). Embedding them is a later optimisation if the inbox needs it.
- Putting the reason in the outbox payload, the email, or audit metadata.
- Editing or withdrawing a decision, or re-opening a rejected offer.
- Backfilling `decided_at` for decisions recorded before the migration.
- Separation of duties (e.g. forbidding the offer creator from approving). Not a rule today; a separate decision.

## Users and use cases

| Actor | Role | Use case |
|---|---|---|
| Hiring manager | `hiring_manager` | Inbox of offers at step 1; open one; approve, or reject with a reason. |
| Tenant admin | `tenant_admin` | Inbox of offers at step 2; same actions. Also reads any offer. |
| Recruiter | `recruiter` | Find the offer for a candidate case and follow its status and history. Inbox is always empty (no step is theirs). |
| Auditor | `auditor` | Read offers and their history. Inbox is always empty. |
| Interviewer | `interviewer` | No access (`403`): has no `tenant:read`. |

## Contract

All routes are tenant-scoped and guarded by `require("tenant:read")`, the same permission the existing `POST /v1/offers/{id}/approvals` uses. The permission check runs before any lookup. Errors use the existing problem+json types in `docs/api-errors.md`; no new types. Timestamps are ISO 8601 with a UTC offset. All `200` responses carry `Cache-Control: private, no-store` (salary is sensitive).

### Shared offer fields

```json
{
  "id": "…",
  "candidate_case_id": "…",
  "title": "Senior Engineer",
  "annual_salary": 120000,
  "currency": "EUR",
  "status": "pending_approval",
  "approval_step": 1,
  "awaiting_role": "hiring_manager",
  "version": 1,
  "can_decide": true
}
```

- `status` is one of `pending_approval`, `approved`, `rejected`.
- `awaiting_role` is `ApprovalPolicy.required_role(approval_step)` while `status = pending_approval`, else `null`.
- `can_decide` is `true` only when `status = pending_approval` and the caller's role equals `awaiting_role`. It mirrors the check in `Offer.decide`, computed by the same policy object, so the UI hides buttons the API would refuse (DUTH-55 AC3). The `POST` keeps enforcing it.

### 1. `GET /v1/offers` — list

Query parameters:

| Name | Type | Default | Rule |
|---|---|---|---|
| `awaiting` | `me` | none | Only offers with `status = pending_approval` at a step whose required role is the caller's role. Any other value → `422`. |
| `candidate_case_id` | string | none | Only the offer for that case. |
| `status` | `pending_approval` \| `approved` \| `rejected` | none | Exact match. Other values → `422`. |
| `cursor` | opaque string | none | `next_cursor` from the previous page. |
| `limit` | integer 1–100 | 25 | Same bounds as `GET /v1/candidate-cases`. |

```json
{"items": [{ "...shared offer fields": "" }], "next_cursor": "…", "total": 3}
```

- Filters combine with AND. A role that owns no step gets `{"items": [], "next_cursor": null, "total": 0}` for `awaiting=me`, never an error.
- The step set for `awaiting=me` comes from `ApprovalPolicy` (a new `steps_for_role(role)`), not from role names in SQL.
- **Order and cursor**: by `id` ascending, keyset `id > :cursor`, `next_cursor` is the last item's id or `null` on the last page — the same scheme as `GET /v1/candidate-cases`. The cursor carries no scope: filters and tenant are re-applied on every page. Offers have no creation timestamp, and adding one is not needed for an inbox of this size.
- `total` counts rows matching the filters, as the candidate list does, so the inbox can show a badge.
- `candidate_case_id` that is unknown or in another tenant returns an empty page, not `404`: the list answers "which offers match", and an empty result reveals nothing.

This is AC3's lookup: a recruiter calls `GET /v1/offers?candidate_case_id={id}`. A case has at most one offer (`offers.candidate_case_id` is unique), so the page has zero or one item. No nested `GET /v1/candidate-cases/{id}/offers` is added: one list route covers both the inbox and the case lookup.

### 2. `GET /v1/offers/{id}` — detail

Shared offer fields plus:

```json
{
  "decisions": [
    {"step": 1, "decision": "approved", "actor_id": "…", "decided_at": "2026-11-26T09:00:00Z", "reason": null},
    {"step": 2, "decision": "rejected", "actor_id": "…", "decided_at": "2026-11-26T10:30:00Z", "reason": "Above band for level"}
  ]
}
```

- `decisions` is ordered by `step` ascending. A step has at most one decision (`uq_approval_decision_offer_step`), and steps are decided in order, so this is also chronological. It does not depend on `decided_at`, which is `null` for legacy rows.
- `actor_id` is the user id, as in every other route; the UI resolves display names.
- `404` (`not-found`) when the id does not exist or belongs to another tenant, with the same body apart from `instance` and `correlation_id`.

### 3. `POST /v1/offers/{id}/approvals` — gains `reason`

```json
{"decision": "rejected", "expected_version": 2, "reason": "Above band for level"}
```

- `reason`: optional string. Leading and trailing whitespace is stripped; then it must be 1–500 characters, or absent/`null`.
- `decision = rejected` with `reason` absent, `null` or blank after stripping → `422` (`validation-error`). Checked in the request model, before any lookup or version check.
- `decision = approved` with a reason stores it; without one stores `null`.
- The reason is stored on the new `ApprovalDecision.reason` column in the same transaction as the decision.
- The response model `OfferResponse` does not change. The client reads history through route 2.
- The outbox event `offer.approval_recorded.v1` keeps its payload exactly as today. The reason is free text that may hold sensitive judgements about a candidate; it stays in the database and route 2 only, and is never logged or put on spans.

### Schema change (expand-only)

One Alembic migration on `approval_decisions`:

| Column | Type | Null | Default | Existing rows |
|---|---|---|---|---|
| `reason` | `String(500)` | yes | none | `null` |
| `decided_at` | `DateTime(timezone=True)` | yes | set by the app (`now_utc`) on insert | `null` |

- Add columns only; no data change, no constraint on existing rows. `downgrade` drops both columns.
- `decided_at` is nullable so the migration never rewrites the table and old app versions keep inserting. The "reason required on reject" rule lives in the API and domain, not as a DB `CHECK`, for the same reason. A later contract migration may make `decided_at` `NOT NULL` after a backfill decision; that is out of scope.
- No index: route 2 reads by `offer_id`, which the unique `(offer_id, step)` constraint already indexes. Route 1 filters on `offers.tenant_id` (indexed) and the `status`/`approval_step` filter over one tenant's offers is small at showcase volume; noted in Risks.

## Acceptance criteria

- AC1: Given offers in tenant A at step 1, step 2, approved and rejected, when a `hiring_manager` in tenant A calls `GET /v1/offers?awaiting=me`, then only the pending step-1 offers are returned; a `tenant_admin` gets only the pending step-2 offers; `recruiter` and `auditor` get an empty page with `total: 0`. Offers in tenant B never appear.
- AC2: Given more matching offers than `limit`, when the caller follows `next_cursor` until it is `null`, then every matching offer appears exactly once, `total` equals the number of matches, and filters still apply on later pages.
- AC3: Given an offer for case X, when a recruiter calls `GET /v1/offers?candidate_case_id=X`, then the page holds exactly that offer. For a case with no offer, an unknown id, or tenant B's case id, the page is empty with `total: 0`.
- AC4: Given an offer approved at step 1 with no reason and rejected at step 2 with a reason, when `GET /v1/offers/{id}` is called, then the response has the shared fields with `status: rejected`, `awaiting_role: null`, `can_decide: false`, and `decisions` in step order with `step, decision, actor_id, decided_at` (UTC offset) and `reason` (`null`, then the text).
- AC5: Given an unknown id or an offer in tenant B, when a caller in tenant A calls `GET /v1/offers/{id}`, then the response is `404` problem+json `not-found`, and the two bodies differ only in `instance` and `correlation_id`.
- AC6: Given a pending step-1 offer, then `can_decide` is `true` for a `hiring_manager` and `false` for `tenant_admin`, `recruiter` and `auditor`, on both routes 1 and 2; after step 1 is approved it is `true` only for `tenant_admin`. For each case, the `POST` agrees: it succeeds exactly when `can_decide` was `true`.
- AC7: Given `decision: rejected` with `reason` absent, `null`, `""` or only whitespace, when the approval is posted, then the response is `422` problem+json, the offer's `version` and `status` are unchanged, and no decision or outbox row is written. A reason over 500 characters after stripping is also `422`.
- AC8: Given `decision: rejected` with a reason, or `approved` with or without one, when the approval succeeds, then `approval_decisions.reason` holds the stripped text (or `null`), `decided_at` is set, and the outbox payload equals `{"offer_id", "decision", "actor_id"}` with no reason key.
- AC9: Given an existing client that posts `{"decision": "approved", "expected_version": n}` with no `reason`, then it behaves exactly as before. Existing offer tests pass unchanged.
- AC10: Given an `interviewer` (no `tenant:read`), when they call routes 1 or 2 with any id, then the response is `403` problem+json `forbidden`.
- AC11: Given `awaiting` other than `me`, `status` outside the three values, or `limit` outside 1–100, then the response is `422` problem+json, never `500`.
- AC12: Given any `200` from routes 1 or 2, then it carries `Cache-Control: private, no-store`.
- AC13: The migration upgrades and downgrades cleanly; rows written before it read back with `reason: null` and `decided_at: null` through route 2.
- AC14: `web/openapi.json` and `web/src/lib/api/schema.ts` are regenerated in the same PR with `make api-client`, and `npm run api:check` in `web/` passes.
- AC15: `ruff format --check`, `ruff check`, `uv run python -m pytest` (coverage ≥ 85%) and the web build pass; actual output is in the PR.

## Constraints

- Hexagonal boundaries (`tests/architecture`): list and detail are queries in `app/modules/offers/application` behind the offer repository port. `can_decide`, `awaiting_role` and `steps_for_role` live on `ApprovalPolicy` / `Offer` in the domain, unit-tested without a database. The reason rule (required on reject, 1–500 chars) is enforced in both the request model and the domain/command, so a non-HTTP caller cannot skip it.
- The routes keep the standard policy injection (`ApprovalPolicy.standard()`) used by the `POST`, so reads and writes use one policy instance.
- Every query filters `tenant_id` on `offers`; the decisions query also filters `approval_decisions.tenant_id`.
- Schema changes through Alembic, expand-only, with the ORM model updated to match so autogenerate stays clean.
- No new environment variables or secrets.

## Risks

- **Salary visible to every `tenant:read` role.** `tenant_admin`, `recruiter`, `auditor` and `hiring_manager` can read salary. This matches the issue (RBAC as the existing read endpoints) and the existing `POST`, which already lets any `tenant:read` role reach an offer by id. If salary should be narrower, that is a permission change for a human to decide, not part of this issue.
- **Reason text leaks.** Mitigation: the reason is not in the outbox, email, audit metadata, logs or spans (AC8), and only route 2 returns it.
- **Legacy decisions show no timestamp.** Accepted: the history order uses `step`, so it stays correct; the UI shows "—" for `decided_at: null`.
- **Inbox query without a dedicated index.** At showcase volume one tenant's offers are a small scan after `ix_offers_tenant_id`. If it grows, add `(tenant_id, status, approval_step, id)` in an expand-only migration.
- **Contract drift with DUTH-55 mocks.** Hiếu-FE builds against this contract; any later change is raised on DUTH-55 first.

## Open questions

None. Decisions beyond the issue text, recorded here for review:

- AC3 uses the `candidate_case_id` filter on the list; no nested route.
- `decided_at` is added alongside `reason`, because the table has no timestamp and AC2 of the issue asks for it.
- `can_decide` and `awaiting_role` are added so DUTH-55 AC3 does not copy the policy into the web app.
- A member has one role per tenant, so `awaiting=me` has no multi-role case.
- The list cursor is the offer id, matching `GET /v1/candidate-cases`; unknown or foreign `candidate_case_id` returns an empty page.
- The reason is 1–500 characters, stripped, and never leaves the database except through route 2.

## Rollout and rollback

- Additive: two new `GET` routes, one optional request field, two nullable columns, regenerated client types. No existing response or permission changes.
- Ship in one PR. After merge, DUTH-55 replaces its mocks with the generated types.
- Rollback: revert the PR and run the migration's `downgrade`. Dropping the columns loses reasons and timestamps recorded since the deploy; the decisions themselves stay.

## Plan

(added at the `plan` step)
