# TalentFlow web

Next.js (App Router) + TypeScript + shadcn/ui. It acts as a backend-for-frontend: Keycloak login with authorization code + PKCE, a server-side session in Redis, and a typed API client generated from the API's OpenAPI document. See [ADR 004](../docs/adr/004-web-bff-session-and-typed-client.md).

## Run

The web app is part of the compose stack: `docker compose up -d && make seed`, then open http://localhost:3000. Sign in with a demo user (`admin@`, `recruiter@`, `manager@` or `interviewer@talentflow.local`, password `dev-demo-password` unless `DEMO_USER_PASSWORD` is set). To use non-default host ports, copy `.env.example` to `.env` and edit `WEB_PORT`, `KEYCLOAK_PORT`, and any other required `*_PORT` values there before running either command. Keep that `.env` file in place for every later `docker compose` and `make seed` call: seeding updates the Keycloak client redirect, web-origin, and logout URLs for `WEB_PORT`.

For a dev server against the compose stack:

```bash
docker compose stop web
cd web && npm ci
API_BASE_URL=http://localhost:8000 REDIS_URL=redis://localhost:6379/1 npm run dev
```

Compose does not publish Redis to the host, so add a `ports` entry for `redis` (for example in a local `compose.override.yaml`) before you run the dev server.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_BASE_URL` | `http://localhost:3000` | Public URL; builds the OIDC redirect and post-logout URIs |
| `API_BASE_URL` | `http://localhost:8000` | API base URL as seen from the web server |
| `OIDC_ISSUER` | `http://localhost:8081/realms/talentflow` | Public Keycloak issuer (browser redirects, `iss` check) |
| `OIDC_INTERNAL_ISSUER` | `OIDC_ISSUER` | Keycloak issuer as seen from the web server (token, JWKS, revocation) |
| `OIDC_CLIENT_ID` | `talentflow-api` | Public OIDC client |
| `REDIS_URL` | `redis://localhost:6379/1` | Session store |

No secrets are required: the client is public (PKCE) and session ids are random.

## Checks

```bash
npm run lint
npm run typecheck
npm test              # vitest; npm run test:coverage for a report
npm run build
make api-client       # from the repo root: regenerate openapi.json and src/lib/api/schema.ts
```

CI fails when `openapi.json` or `src/lib/api/schema.ts` differ from a fresh generation.

## Layout

- `src/lib/auth/`: OIDC flow (`auth-service.ts`), Keycloak endpoints (`identity-provider.ts`), Redis session store
- `src/lib/api/`: generated `schema.ts`, `client.ts` (`openapi-fetch`), `bff-proxy.ts`, `problem.ts` (RFC 9457 presentation)
- `src/lib/actor/`, `src/lib/nav.ts`: caller identity, permissions and role-aware navigation
- `src/app/auth/*`: login, callback and logout route handlers; `src/app/api/tf/[...path]`: BFF proxy
- `src/app/(app)/`: authenticated screens
- `src/lib/pipeline/`, `src/components/pipeline/`: the candidate pipeline board (`/candidates`)
- `src/lib/interviews/`, `src/components/interviews/`: interview scheduling, feedback and calendar links (`/interviews`)
- `src/lib/offers/`, `src/components/offers/`: offer creation and the approval inbox (`/offers`)
- `src/lib/reports/`, `src/components/reports/`: the pipeline reporting dashboard (`/reports`)

## Pipeline board

Each stage column loads its own cursor-paginated page from `GET /v1/candidate-cases?stage=…&requisition_id=…`. A move sends `PATCH /v1/candidate-cases/{id}/stage` with the card's `expected_version`; the card moves only after the API accepts it.

- **Allowed moves**: `src/lib/pipeline/stages.ts` mirrors the backend state machine so the board can make illegal targets non-droppable and keep them out of the keyboard "Move to" menu. `stages.test.ts` parses `candidate_state_machine.py` and fails when the two drift. The API stays the authority (422 on an illegal move).
- **Version conflicts**: a 409 opens a "Changed by someone else" prompt whose only action is to refresh the board. The move is never retried with a newer version, so another user's change is never silently overwritten.
- **Permissions**: without `candidate:transition` the board is read-only; New candidate and New requisition need `candidate:create` and `requisition:create`.
- **Requisitions**: the API has no requisition list yet, so the filter offers requisitions seen on loaded cards or created in this session, and the selected one is kept in `?requisition=`.

## Offers and approval inbox

`/offers` has three lists, each a cursor-paginated `GET`: **Awaiting your approval** (`GET /v1/offers?awaiting=me`), **Ready for an offer** (`GET /v1/candidate-cases?stage=interviewing`, only with `candidate:transition`) and **All offers** (`GET /v1/offers?status=…`). An offer opens in a side sheet (`?offer=<id>`) with its decision history from `GET /v1/offers/{id}`.

- **No policy copy**: the UI never decides who may approve. Approve and Reject render only when the API returns `can_decide: true`, and "Waiting on" comes from `awaiting_role`. `POST /v1/offers/{id}/approvals` stays the authority; a 403 shows a toast and reloads the offer.
- **Reasons**: a rejection needs a reason; any reason is trimmed and limited to 500 characters, checked in the browser and again by the API. Reasons render as plain React text, never HTML or markdown (DUTH-115 threat T15).
- **Conflicts**: a 409 reloads the offer and says someone else changed it. The decision is never retried with a newer version.
- **Legacy decisions** without `decided_at` show "—"; history order comes from `step`.
- **Candidate names** come from `GET /v1/candidate-cases/{id}`, one call per case, cached for the page.

### Typed contract before the generated client

The offer read routes (DUTH-115) and candidate detail (DUTH-110) are specified but not yet in `openapi.json`. `src/lib/offers/contract.ts` declares those routes in the same `paths` shape `openapi-typescript` emits and builds an `openapi-fetch` client over `paths` plus them, so call sites already look like the generated client. Tests run against an in-memory fake of the contract (`test/offers-fake.ts`). Once both routes ship and `make api-client` regenerates `schema.ts`, delete `contract.ts`, import the types from `schema.ts` and use `browserApi()`; `tsc` then flags any field that drifted from the spec. Until then the page shows its error state against a real API.

## Interviews

`/interviews` shows each part only to roles that can use it:

- **Schedule** (`interview:manage`): the dialog's candidate picker shows the first 20 candidates per stage in Screening or Interviewing (`GET /v1/candidate-cases?stage=…&limit=20`) and says "Showing N of M" when there are more. Typing 2 or more characters searches name and email on the server (`q=…`, one request per stage after a 300 ms debounce; only the latest response is applied), so any candidate in those stages can be found. The term is never written to the page URL. The dialog also loads the tenant's interviewers (`GET /v1/interviewers`, shown by email because users have no display name). It converts the local `datetime-local` value to an ISO instant before it sends `POST /v1/candidate-cases/{id}/interviews`. "All interviews" lists `GET /v1/interviews` and can filter by interviewer.
- **My interviews and feedback** (`feedback:submit`): lists `GET /v1/interviews?interviewer=me`. The feedback form checks score, recommendation and comments (1–5000 characters, trimmed) before it calls `POST /v1/interviews/{id}/feedback`, then locks the row. The API enforces one feedback per interview. A 409 says feedback already exists and marks the row as submitted, and the form is not offered again.
- **Calendar link** (`calendar:self`, [DUTH-109](../docs/specs/DUTH-109.md)): `GET /v1/calendar-subscriptions?interviewer=me` lists active links by id and dates only. "Generate link" posts an empty body, so the caller is the interviewer. The feed URL appears once, in a dialog with a copy button, and is held only in component state until the dialog closes. Revoke asks for confirmation; a 404 means the link is already gone and is treated as success.

## Reports

`/reports` needs `report:read`. The server component loads `GET /v1/reports/pipeline`, which returns aggregate counts only, so no candidate names, emails or IDs reach the page.

- **Charts**: candidates by stage, offers by status, and scheduled interviews against submitted feedback. Each chart is a table with decorative bars, so screen readers get the exact numbers. No chart library is added.
- **Ordering**: known stages and offer statuses keep their domain order and show as zero, so charts stay comparable over time. A key the web app does not know yet is appended with a readable label instead of being dropped.
- **States**: a tenant with no candidates, offers or interviews gets an empty state linking to `/candidates`; an API error or 403 renders the Problem Details view with a retry.
