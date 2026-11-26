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

## Pipeline board

Each stage column loads its own cursor-paginated page from `GET /v1/candidate-cases?stage=…&requisition_id=…`. A move sends `PATCH /v1/candidate-cases/{id}/stage` with the card's `expected_version`; the card moves only after the API accepts it.

- **Allowed moves**: `src/lib/pipeline/stages.ts` mirrors the backend state machine so the board can make illegal targets non-droppable and keep them out of the keyboard "Move to" menu. `stages.test.ts` parses `candidate_state_machine.py` and fails when the two drift. The API stays the authority (422 on an illegal move).
- **Version conflicts**: a 409 opens a "Changed by someone else" prompt whose only action is to refresh the board. The move is never retried with a newer version, so another user's change is never silently overwritten.
- **Permissions**: without `candidate:transition` the board is read-only; New candidate and New requisition need `candidate:create` and `requisition:create`.
- **Requisitions**: the API has no requisition list yet, so the filter offers requisitions seen on loaded cards or created in this session, and the selected one is kept in `?requisition=`.
