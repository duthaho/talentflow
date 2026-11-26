# DUTH-122: Search candidates in the interview scheduling picker

## Context and problem

The Schedule interview dialog (DUTH-54, PR #27) loads its candidate options once, when it opens. Checked against `main` at `124379d`:

- `web/src/components/interviews/schedule-interview-dialog.tsx` sends one `GET /v1/candidate-cases?stage=<stage>&limit=100` request for each of `screening` and `interviewing`, merges the results and sorts them by name. `OPTIONS_LIMIT = 100`.
- `GET /v1/candidate-cases` (`app/api/candidate_router.py`) accepts `stage`, `requisition_id`, `cursor` and `limit` (1–100). The picker ignores `next_cursor`, so candidate 101 and later in a stage never appear, and nothing tells the recruiter that the list is incomplete.
- The repository (`SqlAlchemyCandidateRepository.list_page`) filters by tenant, stage and requisition, orders by `id` and returns `total` for the same filters.
- `web/README.md` documents the limit ("the first 100 per stage").

Trung-PM flagged this in the PR #27 code review. Real tenants have more than 100 candidates in these stages, and a recruiter who can't find the candidate can't schedule the interview.

## Goals

- A recruiter finds any Screening or Interviewing candidate by typing part of their name or email, however many candidates the tenant has.
- Search runs on the server, through the existing list endpoint, with unchanged tenant isolation and RBAC.
- The picker never hides results without saying so.
- The web client gets the contract through the regenerated `web/openapi.json` and `web/src/lib/api/schema.ts`.

## Non-goals

- Full-text, fuzzy, typo-tolerant or ranked search. That is the OpenSearch projection in DUTH-66 (stage 7).
- A trigram index (`pg_trgm`) or any other schema change. Not needed at this scale; see Constraints.
- Searching on any other screen (pipeline board, offers). They can adopt the parameter later without a contract change.
- A multi-stage filter (`stage=a,b`). The picker keeps its one-request-per-stage approach.
- Searching on fields other than first name, last name, full name and email.
- Accent-insensitive matching (`nguyen` → `Nguyễn`). It needs `unaccent` or an analyzer, so it belongs with the OpenSearch projection in DUTH-66.

## Users and use cases

| Actor | Role | Use case |
|---|---|---|
| Recruiter | `recruiter` | Opens Schedule interview, types "nguy" or "@acme", picks the candidate, schedules. |
| Tenant admin, hiring manager | roles with `interview:manage` | Same as recruiter. |
| Any caller with `tenant:read` | any role with it | May use `q` on `GET /v1/candidate-cases`. The visible data is the same as today's unfiltered list. |
| Interviewer | `interviewer` | No change: no `tenant:read`, so `403` as today. |

## Contract

### `GET /v1/candidate-cases`: new `q` query parameter

| Parameter | Type | Default | Rules |
|---|---|---|---|
| `q` | string | absent | Optional. Leading and trailing whitespace is trimmed. After trimming it must be 2–100 characters and contain no control characters (Unicode category `Cc`). Otherwise `422`. |

Matching:

- Case-insensitive **substring** match. A case matches when the term occurs in any of `first_name`, `last_name`, `first_name || ' ' || last_name`, or `email`.
- Case folding uses the database's `lower()`. PostgreSQL, the target runtime, folds non-ASCII letters too (`Đ`/`đ`). SQLite folds ASCII only, so non-ASCII case tests run in the PostgreSQL integration suite only. Matching is **not** accent-insensitive: `nguyen` does not find `Nguyễn` (see Non-goals).
- `%`, `_` and `\` in the term are literal characters: they are escaped, never treated as wildcards.
- `q` is ANDed with `stage` and `requisition_id`. The tenant predicate is unchanged and always applied.
- Ordering, the `cursor`/`limit` semantics and the response shape don't change. `total` counts the cases matching every filter, `q` included.
- Omitting `q` returns exactly the same response as today, byte for byte. `openapi.json` changes by design.

Errors use the existing types in `docs/api-errors.md`; no new types:

| Case | Status | Problem type |
|---|---|---|
| `q` shorter than 2 or longer than 100 characters after trimming, empty or whitespace-only, or contains a control character | `422` | `validation-error`, with `errors[].pointer` naming the `q` parameter |
| No token / bad token | `401` | `unauthorized` (unchanged) |
| No `tenant:read` | `403` | unchanged; the permission check runs before validation of `q` |

Example: `GET /v1/candidate-cases?stage=screening&q=nguyen&limit=20` returns `{"items": [...], "next_cursor": null, "total": 3}`.

### Privacy of the search term

The search term is usually a name or an email, so it is PII inside a URL. The request must not leak it into telemetry or logs:

- The OTel server span for `GET /v1/candidate-cases` must not carry the raw `q` value in `url.query`, `http.target`, `http.url` or `url.full`. Redact it to `q=REDACTED` with the existing span hook pattern (`_redact_calendar_feed_span` in `app/shared/observability.py`).
- **Uvicorn access log.** `Dockerfile` runs `uvicorn app.main:app` with the access log on, and uvicorn logs the path *with* the query string. `configure_logging()` in `app/shared/observability.py` attaches a `logging.Filter` to the `uvicorn.access` logger. The filter rewrites the value of every `q` parameter in the logged request line to `REDACTED` and leaves the other parameters as they are. The access log stays on, because it is useful in `docker compose logs api`.
- Prometheus labels already use the route template, so they need no change. No application log line may include `q`.

## Web picker behavior

The candidate `<select>` in `schedule-interview-dialog.tsx` becomes a search field with a result list (a shadcn/ui combobox or the equivalent built from existing primitives). Interviewer loading is unchanged.

1. **Initial state.** When the dialog opens, it loads the first 20 candidates for each schedulable stage with no `q`, so a small tenant works without typing. If either stage's `total` is larger than the rows it returned, the list shows "Showing N of M. Type to search."
2. **Typing.** Fewer than 2 trimmed characters shows the initial list again. With 2 or more, the picker waits for 300 ms of no typing, then sends one request per stage with `q` and `limit=20`.
3. **Stale responses.** Only the response for the latest term is applied. Earlier in-flight requests are aborted or ignored.
4. **States:** a loading indicator while a search is in flight; "No candidates in Screening or Interviewing match '<term>'." when both stages return nothing; an error message with a Retry button when a request fails, using the existing `FormProblem` component. The "Showing N of M" hint shows whenever results are truncated.
5. **Selection.** Each option shows the full name, email and stage. A selected candidate stays selected while the result list changes, and clearing the search does not clear it.
6. **Accessibility.** The search field has a visible label. The list can be used from the keyboard (arrow keys, Enter, Escape), and the result count and states are announced through an `aria-live` region.

The empty-state copy for a tenant with no candidates in either stage stays as it is today.

## Acceptance criteria

- AC1: Given a tenant with more than 100 candidates in Screening or Interviewing, when a recruiter types part of a candidate's first name, last name, full name or email in the picker, then matching candidates from those stages appear, wherever they sit in the list. (Issue AC1)
- AC2: `GET /v1/candidate-cases` accepts `q` as specified above. A case-insensitive substring match runs on the server, `%`/`_`/`\` match literally, and the tenant predicate and the `tenant:read` permission are unchanged. Without `q` the endpoint behaves as before. (Issue AC2)
- AC3: The picker debounces input by 300 ms, applies only the latest response, and shows loading, no-results, truncated ("Showing N of M") and error-with-retry states. (Issue AC2)
- AC4: An invalid `q` (shorter than 2 or longer than 100 characters after trimming, whitespace-only, or containing a control character) returns `422` `validation-error` problem+json. (Issue AC3)
- AC5: API tests cover: a match on each field and on the full name; case-insensitivity; literal `%` and `_`; combination with `stage` and `requisition_id`; `total` and `next_cursor` with `q`; a match in another tenant is never returned (tenant isolation); `403` without `tenant:read`; each `422` case; unchanged behavior without `q`. The matching and escaping cases also run against PostgreSQL in `tests/integration/`, following `test_interview_list_postgres.py`. (Issue AC3)
- AC6: Component tests (Vitest + Testing Library, mocked API) cover: the initial list; no request below 2 characters; one request per stage after the debounce; a stale response doesn't overwrite a newer one; the loading, no-results, truncated and error-with-retry states; the selection is kept while results change. (Issue AC3)
- AC7: The server span for a request with `q` does not contain the raw term. A unit test covers the redaction hook.
- AC8: A `uvicorn.access` record for `GET /v1/candidate-cases?stage=screening&q=<term>` is emitted with `q=REDACTED`, and `stage` stays intact. A unit test sends a record through the configured filter and asserts that the raw term does not appear in the formatted message.
- AC9: `web/openapi.json` and `web/src/lib/api/schema.ts` are regenerated. `web/README.md` no longer mentions the 100-candidate limit and describes the search. (Issue AC4)
- AC10: `ruff format --check`, `ruff check`, `python -m pytest` (coverage ≥ 85%), the web lint, typecheck, tests and build all pass, with the results in the PR.

## Constraints

- **Layering.** `q` is passed through `ListCandidatesQuery` and the `CandidateRepository.list_page` port as a plain string. The escaping and SQL live in the SQLAlchemy adapter only, so `tests/architecture` stays green.
- **Validation.** Validation lives in the API layer (a FastAPI `Query` with `min_length`/`max_length` plus a validator for trimming and control characters), so failures go through the existing RFC 9457 handler.
- **Query.** Use `lower(column) LIKE lower(:term) ESCAPE '\'` (SQLAlchemy `contains(..., autoescape=True)` on `func.lower(...)`), so the same code runs on PostgreSQL and the SQLite test database. No index and no migration: the scan is already bounded by the `tenant_id` index and the stage filter. The picker sends at most 2 requests per 300 ms per user. Indexed and ranked search is DUTH-66's job.
- **One PR.** Quốc-BE (API) and Hiếu-FE (picker) deliver it together, as the issue says. Suggested order: API commit, regenerate the client, picker commit.
- **No new env vars or secrets.**

## Risks

- **Interaction with DUTH-68 (PII encryption, stage 7).** Once names and emails are encrypted with OpenBao transit, `LIKE` over ciphertext stops working, and a blind index supports only exact equality. The DUTH-68 spec must say how `q` keeps working, for example by serving it from the DUTH-66 OpenSearch projection or by accepting exact-match-only email search. I'll add a note on DUTH-68 when this spec is approved, so the contract isn't silently broken.
- **Sequential scans on large tenants.** A leading-wildcard `LIKE` can't use a b-tree index. That's acceptable at showcase scale. If p95 latency on the list endpoint regresses noticeably in the k6 runs (stage 9), add `pg_trgm` GIN indexes through an expand-only migration.
- **PII in URLs.** In the compose stack, the uvicorn access log and the OTel spans are the only places a URL is recorded, and both are redacted (AC7, AC8). A reverse proxy added in front of the API later must apply the same redaction. The web app calls the API with `fetch`, so the term never enters browser history.
- **Enumeration.** A caller with `tenant:read` can already list every case in their tenant, so `q` reveals nothing new. The existing rate limiting still applies.

## Open questions

None. The design choices (parameter name `q`, substring match, 2–100 characters, 20 results per stage, no index) are technical and decided here; spec review can challenge them.

## Rollout and rollback

- **Rollout:** an additive optional parameter. Existing clients and today's picker keep working. No migration and no feature flag.
- **Rollback:** revert the PR. Nothing persists, so there is no data to clean up.

## Plan

(Added at the `plan` step.)
