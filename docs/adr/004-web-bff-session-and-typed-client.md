# ADR 004: Web app as a backend-for-frontend with a server-side session and a generated API client

- **Status:** Accepted
- **Date:** 2026-11-25
- **Issue:** DUTH-51 (parent DUTH-43)

## Context

Stage 3 adds `web/`, a Next.js App Router app. Users sign in through Keycloak and call the FastAPI API, which authorizes each request from a bearer token (`app/modules/identity/security.py`). Two questions need a fixed answer before more screens are built:

1. Where do the OIDC tokens live, and who attaches them to API calls?
2. How do TypeScript types stay in step with the API contract?

## Decision

**Backend-for-frontend (BFF) session.** The Next.js server is the OIDC client. It runs the authorization code flow with PKCE (S256), `state` and `nonce`, using `openid-client` (`web/src/lib/auth/`). Tokens are stored in Redis under a hash of a random 256-bit session id. The browser receives only that id, in an `httpOnly`, `SameSite=Lax` browser-session cookie (`Secure` on https) with no `Max-Age`: Redis owns the session lifetime, and each token refresh extends the Redis TTL to Keycloak's `refresh_expires_in`. Browser code calls the API through `/api/tf/v1/*`, a route handler that adds the bearer token and forwards an allow-list of headers (`web/src/lib/api/bff-proxy.ts`). Server components call the API directly with the same token.

- Access tokens are refreshed on the server 30 s before they expire. Only an `invalid_grant` answer ends the session. When Keycloak is unreachable or returns another error, the session is kept: a still-valid access token continues to be used, and otherwise the user sees a 503 service-unavailable problem until the next refresh succeeds.
- Logout accepts only same-origin form posts (`Origin`/`Sec-Fetch-Site`, as the proxy does for unsafe methods). It deletes the Redis session, revokes the refresh token and redirects to Keycloak's end-session endpoint with `id_token_hint`. The Keycloak client allows only `/auth/callback` as a redirect URI and `/signed-out` as the post-logout URI, and requires S256 PKCE.
- In compose, the browser uses Keycloak's public issuer (`localhost:8081`), while the web server calls the token, JWKS and revocation endpoints on `keycloak:8080`. The OIDC metadata is built explicitly (`keycloakMetadata`) because discovery would return only public URLs.

**Contract-first typed client.** `make api-client` exports the FastAPI OpenAPI document to `web/openapi.json` (`scripts/export_openapi.py`) and generates `web/src/lib/api/schema.ts` with `openapi-typescript`. Both files are committed. The CI `web` job regenerates them and fails on any diff. Calls use `openapi-fetch`, so paths, parameters and response bodies are type-checked.

**One error presentation.** Every API failure becomes RFC 9457 Problem Details (`web/src/lib/api/problem.ts`). Network failures and non-problem bodies are mapped to a fallback problem. `describeProblem` maps the problem `type` (or the status) to a single title, description, field errors and correlation id. Pages render it with `ProblemView`; client actions show it with `toastProblem`.

**Role-aware navigation.** The nav is derived from the caller's permission set (`web/src/lib/nav.ts`). It is a usability aid only: the API remains the authority and returns 403. The API does not yet expose the caller's role, so `ACTOR_SOURCE=mock` resolves demo memberships from a typed mock that mirrors `ROLE_PERMISSIONS` (`web/src/lib/actor/mock.ts`). The intended contract is `GET /v1/me` (`web/src/lib/actor/current-actor.ts`); when the API serves it, set `ACTOR_SOURCE=api` and delete the mock.

## Consequences

- No token reaches browser JavaScript or web storage, so an XSS bug cannot exfiltrate a token. It can still act as the user through the BFF while the page is open; CSP hardening is stage 9.
- Sessions can be revoked server-side, and token size does not hit cookie limits.
- The web server needs Redis (database 1) and becomes a hop on every browser API call.
- API changes that alter the OpenAPI document require `make api-client` in the same PR, or CI fails.
- Until `GET /v1/me` exists, role-aware nav works for the seeded demo users only.

## Rejected alternatives

- **Public SPA client with tokens in the browser** (for example `oidc-client-ts` with `sessionStorage`): simpler, but tokens are readable by any script on the page, and refresh tokens in the browser need rotation and sender constraints.
- **Auth.js (`next-auth` v5)**: v5 is still a beta release, and its discovery-based Keycloak provider does not support the public/internal endpoint split without custom configuration.
- **Encrypted cookie session (iron-session style)**: no Redis dependency, but Keycloak's access, refresh and ID tokens together exceed the 4 KB cookie limit, and a stolen cookie cannot be revoked.
- **Hand-written API types**: drift silently from the API.

## Revisit when

- The API serves `GET /v1/me` (remove the mock).
- The app is served from more than one origin, or needs offline or mobile clients.
