# Onboarding operations

The API and worker implement stage 1 of [DUTH-64](specs/DUTH-64.md).
The candidate page panel and browser E2E are planned for DUTH-153 (stage 2).
The hire remains `hired` even if onboarding compensates.

## Run locally

Use `docker compose up -d --build onboarding-worker notification-worker outbox-relay`.
The dependencies include the internal HRIS stub and the imported `employees` realm.
The release flag `release.onboarding.saga` defaults off; the demo tenant is targeted on.
`GET /v1/me` exposes `features.onboarding`. Provisioning secrets belong only to the
onboarding worker; `HRIS_STUB_TOKEN` also belongs to the stub. Public development
credentials in Compose are examples, and production rejects them.

Configuration names: `KEYCLOAK_ADMIN_URL`, `KEYCLOAK_ONBOARDING_REALM`,
`KEYCLOAK_ONBOARDING_CLIENT_ID`, `KEYCLOAK_ONBOARDING_CLIENT_SECRET`,
`HRIS_STUB_URL`, `HRIS_STUB_TOKEN`, `ONBOARDING_FAULT_INJECTION`, and existing
`WORKER_*` settings. Production provisioning requires HTTPS and private secrets.
The API does not load worker provisioning credentials.

For a compensation demo, set `ONBOARDING_FAULT_INJECTION=provision_account` and
recreate the worker with `docker compose up -d --force-recreate onboarding-worker`.
Hire an approved candidate in an enabled tenant. The real retries remain
10/30/120/300 seconds; compensation starts after all five attempts fail.
The employee is removed, and the saga ends `compensated`. Clear the setting and
recreate the worker before an admin retry. The allowed names are `create_employee`,
`provision_account`, `schedule_tasks`, `notify`; unknown names fail startup.
Injection is accepted only in development/test. A notify failure ends
`completed_with_warnings`, retaining employee, account and tasks.

## API contract

The executable contract is `/openapi.json` (`app/api/onboarding_router.py`).
`PATCH /v1/candidate-cases/{id}/stage` accepts `start_date` only for `hired`,
from today through today +365 UTC inclusive. An omitted date resolves from the
hire event's UTC date +14, even when consumed later.

`GET /v1/candidate-cases/{id}/onboarding` returns the current attempt, steps,
tasks, warning and actor-specific `actions`, with `ETag`. It remains readable when
the gate turns off. Earlier attempts remain in PostgreSQL and action audit.
Retry/cancel return 202 and require `If-Match`; use an `Idempotency-Key` to replay
a successful command. Error order: 401, role 403, ownership 404, feature 403,
428/412, state 409. Retry is allowed only from `compensated`, before erasure,
up to five saga attempts. Cancel is allowed only before tasks commit (the pivot).
The response schema and fault setup are the stage-2 integration contract.

## Recovery R6: skipped hires during a flag outage

Recovery is limited to events younger than **30 days**, the inbox retention
window. Enabling the flag does not backfill inboxed hires. On an operator-owned
local/disposable stack, confirm the case is still hired, not anonymized, and has
neither a saga nor an erasure tombstone. Re-enable the tenant flag. Find the original
`candidate_case.stage_changed.v1` event and its original envelope/ids in the outbox.
In a controlled transaction remove only `inbox_messages` matching
`consumer='onboarding'` **and that exact event id**. Republish the original envelope
directly to `onboarding.events`, using the procedure in
[events/operations.md](events/operations.md). Do not republish to the exchange:
other consumers have already processed it. Verify a single saga starts; repeat
recovery cannot create a second saga because `(tenant_id,candidate_case_id)` is
unique. Never remove erasure tombstones or reset the whole inbox.
This procedure is not authorization for an agent to write a shared database.

## Compensation failure and erasure (S10)

`compensation_failed` stops automatic progression. Read `last_error` (a symbolic
class/code only), the failed step's `compensation_status`, and its `external_ref`
from the operator's database view. Confirm ownership by saga id before manual
cleanup: the HRIS key is the saga id; Keycloak username is `tf-<case-id>` and the
`onboarding_saga_id` attribute must match. Never delete a directory account with a
missing/different attribute. HTTP delete and missing-resource 404 are idempotent.
Record external cleanup in the incident/DSAR record; do not pretend manual cleanup
has restarted the stopped saga. Retry through the API is limited to `compensated`.

Candidate erasure before the pivot requests compensation, including any ambiguous
in-flight effect after its lease expires. Every subsequent candidate read is
suppressed. After the pivot, notify is skipped; existing HRIS/directory records are
retained under decision R4. **Every erasure request for a hired person must be
forwarded to the HRIS and directory owner using the external reference ids**.
This is also the DUTH-69 DSAR handoff rule; deleting/anonymizing the recruiting case
does not erase downstream employment data. Erasing a `compensation_failed` saga
records the audit event and counter `onboarding_erasure_cleanup_required` (saga id
only in logs), requiring the same owner to remove any stranded PII.

## Observe and verify

The worker exposes `/health/live`, `/health/ready`, `/metrics` on internal port
8005. Metrics use bounded `status`, `step`, `outcome` labels:
`talentflow_onboarding_sagas_total`, `talentflow_onboarding_step_attempts_total`,
`talentflow_onboarding_running`; consumer outcomes include `skipped_flag_off`.
A messaging dashboard row shows outcomes and active sagas.

`scripts/verify_onboarding.sh` builds the changed images, starts an isolated stack,
verifies a healthy worker, runs migrations and all onboarding acceptance tests
against PostgreSQL, RabbitMQ, Keycloak, HRIS and Mailpit, and tears down only its
own containers/volumes. It uses a dedicated broker vhost and per-test DB schemas.
The crash tests kill a child after the remote effect and before outcome commit.
Do not count skipped service tests as acceptance evidence. Set
`ONBOARDING_VERIFY_FULL=1` to run the whole backend suite with those endpoints.
