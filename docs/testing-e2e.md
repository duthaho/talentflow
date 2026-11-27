# Hiring E2E tests

`web/e2e/hiring.spec.ts` runs Chromium against the production Compose web app,
Keycloak, API, PostgreSQL and notification worker. It uses actual OIDC logins and
browser forms; it does not mock API responses or inject session cookies.

From the repository root:

```sh
export COMPOSE_PROJECT_NAME=talentflow-e2e
export COMPOSE_FILE=docker-compose.yml:docker-compose.e2e.yml
docker compose up --detach --build --wait api web notification-worker
make seed
uv sync --python 3.13 --frozen
npm --prefix web ci
make api-client
cd web
npx playwright install --with-deps chromium
npm run test:e2e
```

Run this against an isolated local demo stack. The tests create synthetic
requisitions/candidates with unique names and leave their records for inspection.
They never purge Mailpit. To remove a disposable stack, run
`docker compose --profile workers down --volumes` from the root with the same
project name and ports. Include the workers profile during cleanup so the
explicitly started notification worker is removed too.

For shared runners, export `COMPOSE_PROJECT_NAME` and all nine host-port variables
before starting Compose: `POSTGRES_PORT`, `MAILPIT_PORT`, `KEYCLOAK_PORT`,
`SEAWEEDFS_PORT`, `OTEL_GRPC_PORT`, `OTEL_METRICS_PORT`, `GRAFANA_PORT`, `API_PORT`,
and `WEB_PORT`. The same `WEB_PORT` and `MAILPIT_PORT` values configure
Playwright. `E2E_BASE_URL` and `E2E_MAILPIT_URL` can override those two derived URLs.
`DEMO_USER_PASSWORD` must match the value used by the seed command if overridden.
All accounts are the local demo identities documented in the quick start.

The two acceptance scenarios are:

- **DUTH-57 AC1:** recruiter opens a requisition and creates a candidate, moves to
  Screening, schedules an interview; interviewer submits feedback and sees it
  locked after reload; recruiter moves to Interviewing and creates an offer;
  manager approves step 1, admin approves step 2; recruiter moves to Hired and
  reloads. The test checks that hiring is unavailable between approvals, both
  approval decisions persist, new approval emails reach both actors through the
  worker, their bodies say approved, and the subject appears in Mailpit's UI.
  The current adapter emails the approval actor, rather than the candidate, and
  has a generic subject/body. New message IDs and recipients distinguish these
  deliveries from mail already in the inbox; isolate the stack from other writers.
- **DUTH-57 AC3:** two independent recruiter sessions read the same candidate.
  One commits Screening; the other tries Rejected with the original version.
  The actual API returns 409 Problem Details, the conflict prompt appears, and
  Refresh board shows Screening. A subsequent move uses the refreshed version.

**AC2:** the `hiring-e2e` job in `.github/workflows/ci.yml` runs on every PR and
push to `main`, with non-default host ports. It starts the notification worker
explicitly (the normal stack excludes the workers profile). No retries are used;
web assertions wait for observable state and email polling is bounded at 30s.

Playwright records all actor contexts. On failure, it retains a combined trace
and page screenshots under `web/test-results/`; it also writes an HTML report.
CI uploads these plus Compose status/logs for seven days. Locally open a report
with `npx playwright show-report`, or a trace with
`npx playwright show-trace test-results/<test>/trace.zip`.
Artifacts contain local demo login/session data; use only synthetic local data.

The suite uses one worker to keep the workflow ordered and isolate Mailpit
observations. It starts neither a development server nor its own infrastructure;
Compose readiness and seed must finish before running it.

The test-only Compose override gives the API a 1,000-request/minute budget while
keeping rate limiting enabled. All actors share the BFF container's source IP;
the board fetches each stage separately, so the two scenarios can exceed the
normal 120-request budget on fast CI runners. The default Compose runtime keeps
its normal limit. Rate-limiter semantics remain covered by the backend suite.
