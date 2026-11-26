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
| `candidate_case_id` | string, max 64 chars | none | Only the offer for that case. Longer → `422`. |
| `status` | `pending_approval` \| `approved` \| `rejected` | none | Exact match. Other values → `422`. |
| `cursor` | opaque string, max 64 chars | none | `next_cursor` from the previous page. Longer → `422`. |
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

- `reason`: optional string. Leading and trailing whitespace is stripped first; the 1–500 character limit applies to the stripped value. Absent or `null` means no reason.
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
- AC11: Given `awaiting` other than `me`, `status` outside the three values, `limit` outside 1–100, or a `cursor` or `candidate_case_id` longer than 64 characters, then the response is `422` problem+json, never `500`.
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

- **Salary visible to every `tenant:read` role (Medium, T12).** `tenant_admin`, `recruiter`, `auditor` and `hiring_manager` can read salary. These are the first routes that return it: `OfferResponse` has no salary field. No hiring manager is tied to a requisition, so every hiring manager sees every offer's salary in the tenant. This matches the issue (RBAC as the existing read endpoints), and approvers need salary to decide. It ships only with duthaho's explicit risk acceptance at plan approval. Otherwise the plan first needs an `offer:read` permission, or `annual_salary` omitted for roles outside the approval chain. Either is a separate issue.
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
- Rollback, in this order: deploy the reverted code first, then run the migration's `downgrade`. The old code never reads or writes the new columns, so it runs safely on the expanded schema; downgrading first would break the new code still serving. Dropping the columns loses reasons and timestamps recorded since the deploy; the decisions themselves stay.

## Plan

### Design summary

Two read routes and one optional request field on the existing offers context, plus two nullable columns. No new module, permission or cross-context dependency. The contract above is the design; this table says where each piece lives.

| Layer | File | Change |
|---|---|---|
| Domain | `app/modules/offers/domain/approval_policy.py` | `steps_for_role(role) -> frozenset[int]` and `awaiting_role(offer) -> str \| None` (role for `approval_step` while `pending_approval`, else `None`). |
| Domain | `app/modules/offers/domain/offer.py` | `can_be_decided_by(role, policy) -> bool`, used by both `decide()` and the read model, so the read flag and the write check cannot drift. `decide()` takes `reason: str \| None` and raises `InvalidOfferApprovalError` when a rejection has no reason after stripping, or the reason is longer than 500 characters; `OfferDecision` carries the reason. |
| Application | `app/modules/offers/application/list_offers.py` (new) | `ListOffersQuery(tenant_id, actor_role, awaiting_me, candidate_case_id, status, cursor, limit)` and handler. With `awaiting_me` it asks the policy for the role's steps; an empty set returns an empty page without a query. Returns `OfferPage(items, next_cursor, total)` of `OfferView`. |
| Application | `app/modules/offers/application/get_offer.py` (new) | `GetOfferQuery(tenant_id, offer_id, actor_role)` returns `OfferDetailView` with `decisions: list[DecisionView]` or raises `OfferNotFoundError`. `awaiting_role`/`can_decide` are computed here from the policy. |
| Application | `decide_offer.py`, `ports.py` | `DecideOfferCommand.reason`; `record_decision(..., reason)`. `record_outbox_event` signature and payload are unchanged. Port gains `list(...)`, `get_detail(...)` and `list_decisions(offer_id, tenant_id)`. |
| Infrastructure | `app/modules/offers/infrastructure/models.py`, `sqlalchemy_repository.py` | `ApprovalDecision.reason` (`String(500)`, nullable) and `decided_at` (`DateTime(timezone=True)`, nullable, `default=now_utc` with a module-local `now_utc` as every other context defines). List query: `WHERE tenant_id = :t` plus optional `status`, `candidate_case_id`, `approval_step IN (:steps) AND status = 'pending_approval'`, `id > :cursor`, `ORDER BY id LIMIT limit+1`, and a `COUNT` with the same filters minus the cursor (as the candidate list does). Decisions: `WHERE offer_id = :o AND tenant_id = :t ORDER BY step`. |
| Migration | `migrations/versions/<rev>_add_approval_decision_reason.py` (new) | `add_column` × 2, both nullable, no server default and no backfill; `downgrade` drops both. `down_revision` is the current `alembic heads`. |
| API | `app/api/offer_router.py`, `app/api/schemas.py` | `GET /v1/offers` (registered before `GET /v1/offers/{offer_id}`) and `GET /v1/offers/{offer_id}`, both `require("tenant:read")` and `ApprovalPolicy.standard()`. `awaiting: Literal["me"] \| None`, `status: Literal[...] \| None`, `limit: int = Query(25, ge=1, le=100)`. `ApproveOfferRequest.reason` with a `model_validator` (strip, then length and reject-requires-reason; static error messages that never include the value, T14). Responses set `Cache-Control: private, no-store` as `calendar_router` does. New models: `OfferSummaryResponse`, `OfferPageResponse`, `OfferDecisionResponse`, `OfferDetailResponse`. `OfferResponse` unchanged. |
| Client | `web/openapi.json`, `web/src/lib/api/schema.ts` | `make api-client`. |
| Docs | `docs/architecture.md` (offers context), README pattern catalog | One line: approval policy drives both the write check and the read `can_decide` flag. |

The reason rule sits in the request model (fast `422` before any lookup) and in `Offer.decide` (no non-HTTP caller can skip it). A domain `InvalidOfferApprovalError` caused by the reason maps to `422`, not the `403` used for a wrong role: the handler raises a distinct `InvalidOfferReasonError` subclass so the router can tell them apart.

### Test plan

| AC | Test | Level |
|---|---|---|
| AC1 | seed tenant A with offers at step 1, step 2, approved, rejected, and one tenant-B offer at step 1; `awaiting=me` as each of the four `tenant:read` roles; assert exact id sets and `total` | integration `tests/integration/test_offer_read.py` |
| AC2 | 5 matching offers, `limit=2` walk: no duplicates or gaps, `total=5` on every page, a `status` filter still applied on page 3 | integration |
| AC3 | `candidate_case_id` for a case with an offer, a case without one, an unknown id and a tenant-B case id | integration |
| AC4 | approve step 1 without a reason, reject step 2 with one; detail has shared fields, `awaiting_role: null`, `can_decide: false`, two decisions in step order, `decided_at` with a UTC offset | integration |
| AC5 | unknown id vs tenant-B id: both `404` `not-found`, bodies equal except `instance`/`correlation_id` | integration |
| AC6 | for each role × offer state, `can_decide` from GET equals whether the following POST succeeds (`200`) or fails (`403`) | integration, parametrized; unit on `can_be_decided_by` and `steps_for_role` |
| AC7 | reject with reason absent / `null` / `""` / `"   "` / 501 chars after stripping → `422`; offer `version`/`status`, decision count and outbox count unchanged; a 500-char reason with surrounding spaces is accepted | integration + unit on `Offer.decide` |
| AC8 | stored `reason` is the stripped text, `decided_at` set; outbox `payload_json` keys equal exactly `{"offer_id", "decision", "actor_id"}` | integration (extend `test_approval_outbox.py`) |
| AC9 | existing `test_offer_approval.py` and `test_approval_outbox.py` untouched and green | existing |
| AC10 | `interviewer` on both routes with a real and an unknown id → `403` `forbidden` | integration |
| AC11 | `awaiting=you`, `status=draft`, `limit=0`/`101`, a 65-char `cursor` and `candidate_case_id` → `422` problem+json | integration |
| AC12 | header asserted on both routes | integration |
| AC13 | insert a decision without the new columns (raw SQL), read it through the detail route → `reason`/`decided_at` `null`; `alembic upgrade head` then `downgrade -1` against the compose Postgres, output in the PR | integration + manual |
| AC14 | `npm run api:check` in `web/` (CI `web` job and locally) | CI |
| AC15 | gates below | local + CI |
| — | architecture rule green with no new entries | existing |

Gates before hand-off: `ruff format --check`, `ruff check`, `uv run python -m pytest` (coverage ≥ 85%), `npm run api:check` and `npm run build` in `web/`.

### Threat model

From Hoàng-Security on DUTH-115, against spec `4da6ec8`. Routes 1 and 2 are the first routes that expose salary, so T12 is the one finding that needs a human decision.

| # | STRIDE | Threat | Control | Covered by |
|---|---|---|---|---|
| T1 | I | Reading another tenant's offer or decision history by id | `WHERE id = :id AND tenant_id = :t` on `offers`; decisions also filtered on `approval_decisions.tenant_id`, never joined by `offer_id` alone | AC5 |
| T2 | I | Probing which offer ids exist in other tenants | One query, same 404 body for unknown and foreign ids | AC5 |
| T3 | I | `candidate_case_id` filter confirms a case exists in another tenant | Filter ANDed with `offers.tenant_id`; unknown and foreign ids both return an empty page with `total: 0` | AC3 |
| T4 | I | Inbox leaks offers across tenants | Tenant predicate on both the page query and the `COUNT` | AC1 |
| T5 | T/I | Forged cursor reaches out-of-scope offers | Cursor is only a keyset bound (`id > :cursor`) on top of the tenant and filter predicates, so no signature is needed. A plain id reveals nothing the caller can't already see | AC2 |
| T6 | T | SQL injection through `cursor`, `candidate_case_id`, `status` or `awaiting` | Bound parameters only, `Literal` types for enums, no interpolated `text()` | AC11, security review |
| T7 | D | Huge or malformed cursor causes a 500 | Cursor is compared as a string, so no decode step. Length cap on `cursor` and `candidate_case_id` (e.g. `max_length=64`) → 422 | AC11 (add the cursor case) |
| T8 | D | Expensive list scans | `limit` 1–100, `ix_offers_tenant_id`, global rate limit. `COUNT` per page accepted at showcase volume (Low) | AC11, Risks |
| T9 | E | A role decides a step it doesn't own | `POST` still runs `Offer.decide` through `can_be_decided_by`; `can_decide` is display-only | AC6 |
| T10 | I | `can_decide` / `awaiting_role` disclose the approval policy | Accepted (Low): the policy is static, tenant-wide and not secret; the `POST` stays authoritative | AC6 |
| T11 | E | Interviewer reads offers | `require("tenant:read")` before any lookup; `ROLE_PERMISSIONS` unchanged | AC10 |
| T12 | I | Salary visible to every `tenant:read` role, including every hiring manager tenant-wide | **Medium, needs human risk acceptance.** Authenticated, same-tenant staff only; cross-tenant is covered by T1–T4. Follow-up if narrower: an `offer:read` permission, or omit `annual_salary` for roles outside the approval chain | Plan approval (duthaho) |
| T13 | I | Free-text `reason` leaks through outbox, email, audit metadata, logs or spans | Outbox payload keys fixed to `{offer_id, decision, actor_id}`; reason not on `DecideOfferCommand` logging, audit metadata or span attributes; only route 2 returns it | AC8 |
| T14 | I | `reason` echoed back in a 422 body or log line | The handler emits only `loc` and `msg`, not `input`. Validator messages must be static: no f-string with the value | AC7, security review |
| T15 | T | Stored XSS through `reason` in the inbox | Stored as plain text; the API returns JSON. DUTH-55 must render it as text (no `dangerouslySetInnerHTML` / markdown) | DUTH-55 |
| T16 | T | Non-HTTP caller skips the reject-needs-reason rule | Rule enforced in both the request model and `Offer.decide` | AC7 (unit on `Offer.decide`) |
| T17 | I | Browser or proxy caches salary or reasons | `Cache-Control: private, no-store` on every `200` | AC12 |
| T18 | I | Future ORM columns leak | Explicit response models; `OfferResponse` unchanged | AC4 |
| T19 | R | Decisions without a timestamp | `decided_at` set by the app on insert; legacy rows are `null` and ordered by `step` | AC8, AC13 |
| T20 | R | Reads of salary are not audited | Accepted (Low): no read route is audited today; separate follow-up if read auditing becomes a goal | — |
| T21 | T | Migration rewrites or locks `approval_decisions` | Expand-only: two nullable columns, no server default, no backfill, no `CHECK` | AC13 |

`security_review` on the implementation PR stays required. It checks:

- the tenant predicate on `offers` and `approval_decisions` in every query, including the `COUNT`;
- that the foreign `candidate_case_id` and foreign-id tests run against a real second tenant;
- bound parameters only;
- the 64-character caps on `cursor` and `candidate_case_id`;
- that `can_decide` and `decide()` share `can_be_decided_by`;
- that `reason` appears in no outbox payload, audit metadata, `logger.*` call, span attribute or validator message (grep the diff);
- that a reason error maps to `422` and a wrong role still maps to `403`;
- `Cache-Control` on both routes;
- the migration diff;
- `pip-audit` and a secret scan.

A gap in AC3, AC5, AC6, AC8, T1 or T13 is a blocking High.

DUTH-55 must render `reason` as plain text, with no HTML or markdown rendering (T15).

### Sub-issues by stage

None. The two routes and the reason field are one API slice for one page, with one PR to review and verify, so the work ships as one PR on DUTH-115 itself.

| Stage | Work | Handler | ACs | Depends on |
|---|---|---|---|---|
| 1 | Implement the routes, reason field, migration, tests, regenerated client and docs. PR titled `DUTH-115: Add offer read APIs and decision reasons`, linking this spec | Quốc-BE | AC1–AC15 | spec PR #19 approved (done); requester approves this plan |
| review | `code_review` → `security_review` (required: salary exposure, free-text reason, cross-tenant reads) → `qa` → `in_review` | Trung-PM, Hoàng-Security, Diễm-QA | — | stage 1 PR |

Downstream: when this issue moves to `in_progress`, DUTH-55 starts in the same step (`in_progress`, Hiếu-FE) against typed mocks of this contract, as the issue notes ask. It switches to the generated types once the stage 1 PR merges.
