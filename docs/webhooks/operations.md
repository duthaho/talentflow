# Outbound webhook operations

DUTH-62 implements the backend of [ADR-008](../adr/008-outbound-webhooks.md).
The admin screens are DUTH-141. The tenant-admin API is described in
[OpenAPI](openapi.yaml); the same paths and schemas ship in `/openapi.json`.

## Local demo

Start the normal Compose stack and seed it as described in the root README.
`webhook-worker` consumes `webhooks.events` and sends due HTTP deliveries. It
exposes its worker readiness probe on container port 8004 (`/health/ready`).
The `webhook-demo` sink listens on port 8080 only inside its dedicated bridge;
register `http://webhook-demo:8080/events` through `POST /v1/webhook-endpoints`
with the tenant-admin access token and an explicit `event_types` list. It returns
`secret: {id, value}` once. Keep the value in the receiver's secret store.

Or use the web app: sign in as the tenant admin and open **Settings → Webhooks**
(`/settings/webhooks`). It lists, creates, edits, disables, deletes and rotates
endpoints, shows each secret once in a dialog that discards it on close, and has
a per-endpoint delivery log with a status filter (for example Dead-lettered) and
a Redeliver action that follows the new delivery until it finishes. Only roles
with `webhook:manage` see the screen; the API enforces the same permission.

The demo sink accepts requests to demonstrate transport; it does not authenticate
messages. Real receivers must verify the raw body and replay window using the
[ADR-008 sample verifier](../adr/008-outbound-webhooks.md#2-signing-standard-webhooks-hmac-sha256)
or `app.modules.webhooks.application.signing.verify`, then deduplicate
`webhook-id` before applying effects. Retries and manual redeliveries keep that id.

Compose supplies a **public development-only** encryption key, enables HTTP and
allowlists the demo bridge. `WEBHOOK_DEMO_SUBNET` changes both the bridge subnet
and its allowlist if the default overlaps another local network. Production
rejects HTTP, private allowlists and the development key (including renamed copies).

## Keys and rotation

The required configuration names are `WEBHOOK_SECRET_KEYS` and
`WEBHOOK_SECRET_ACTIVE_KEY_ID`. Supply a comma-separated keyring of
`kid:base64-of-32-random-bytes` through the environment/secret manager. Never put
real keys in Compose, source control, command history, logs or issue comments.
Other settings are `WEBHOOK_ALLOW_HTTP`, `WEBHOOK_PRIVATE_NETWORK_ALLOWLIST`
and `WEBHOOK_DELIVERY_RETENTION_DAYS` (default 30). The API and workers must share
all decrypt keys and the same active key id. With `APP_ENV=production`, both
`WEBHOOK_SECRET_KEYS` and `WEBHOOK_SECRET_ACTIVE_KEY_ID` are required on the API,
migration commands and every worker container; the development defaults are not
valid production configuration. The CI `container-smoke` job generates one masked,
throwaway keyring and forwards both variables to every container in that job.

Signing-secret rotation uses `POST /v1/webhook-endpoints/{id}/secret-rotations`
with a concrete `If-Match` ETag and optional `grace_period_seconds` (default 86400).
Install the returned secret at the receiver. Both old and new keys sign during
the grace period; use grace 0 to revoke a compromised key immediately. GET returns
only active secret metadata. Create and rotation deliberately ignore Idempotency-Key;
rotation's concrete ETag prevents a retry from issuing another secret.

To rotate the encryption key without changing receivers' signing secrets:

1. Add the new encryption key to the ring on the API and workers, keeping every
   old key available. Set the active id to the new key and restart them.
2. Run `python -m app.workers.webhook_secret_rewrap` in the same configured
   environment (for Compose, `docker compose run --rm webhook-worker python -m
   app.workers.webhook_secret_rewrap`). It uses bounded `FOR UPDATE SKIP LOCKED`
   batches and never prints keys or ciphertext. Confirm all live rows have the
   active `key_id`; do not remove an old key while another rewrap process may hold
   skipped rows.
3. Remove the old encryption key only after rewrap completes everywhere. Keep
   required keys available for backups according to the backup/restore policy.

DUTH-68 can implement the same `WebhookSecretCipher` port with OpenBao; this
implementation does not require OpenBao. The URL is currently plaintext in the
database: authenticate receivers with signatures, not URL query tokens.

## Failures and recovery

The RabbitMQ inbox transaction only creates event/delivery rows. Its retries and
DLQ cover database failures. The HTTP worker separately claims deliveries for
60 seconds, sends outside the transaction, and records the result. It pins the
validated IP while preserving Host/TLS SNI, disables proxies and redirects, and
bounds DNS, connect, total attempt time, request size and response reads.

List an endpoint's delivery log with `GET /v1/webhook-endpoints/{id}/deliveries`.
Filters include repeated `status`, `event_type`, `event_id` and the half-open
`created_from`/`created_to` range. Follow `next_cursor` without interpreting it.
`GET /v1/webhook-deliveries/{id}` includes attempts, status codes and safe error
enums; receiver bodies and headers are never retained. Malformed status lines,
missing signing keys and decryption failures record a failed attempt using the
existing `connect_error` enum, clear its lease and follow the same backoff and
eight-attempt cap. Signing failures never send an unsigned/partially signed
request. Safe warning logs identify the delivery, error stage and exception class,
without the exception text, ciphertext or key material.

Eight failed attempts dead-letter a delivery. `410` dead-letters immediately and
disables the endpoint. Sustained failures disable it only after both 20 failures
and 72 hours. Inspect `disabled_reason`, fix the receiver, then PATCH `enabled:
true` using the current ETag. Disable/delete cancels pending deliveries; re-enable
does not revive them. A URL update applies to the next attempt of existing work.

`POST /v1/webhook-deliveries/{id}/redeliveries` queues a new delivery from a
terminal one while preserving the original log. Use Idempotency-Key for safe
retries; a simultaneous pending delivery returns 409. PATCH also supports
Idempotency-Key and includes the raw If-Match in its fingerprint.

The metric `talentflow_webhook_deliveries_total` counts `pending` retries and
terminal outcomes, including `dead_lettered`. An expected duplicate after a crash
is absorbed by the receiver's `webhook-id` deduplication. A lease fences stale
worker results, and at most four leases per endpoint may be active across replicas.

The retention worker purges terminal deliveries after the configured horizon in
bounded batches. Attempts follow their delivery; redelivery lineage becomes NULL
when its original is purged, while `kind=redelivery` remains immutable. Unreferenced
event bodies and tombstones are removed separately. Previous signing-key
ciphertexts are erased when their grace period expires.

## Development and verification

`cryptography` is a direct runtime dependency for AES-256-GCM. `dnspython` supplies
cancellable async A/AAAA queries: a timed-out libc resolver thread could otherwise
extend `asyncio.run` shutdown beyond the delivery deadline. The HTTP transport uses
standard-library async streams and TLS and does not resolve a hostname again after
validation.

After changing the approved contract, run `uv run python -m
scripts.sync_webhook_contract`, format `app/api/webhook_contract.py` with Ruff,
then run `uv run python -m scripts.export_openapi` and
`npm --prefix web run api:generate`. The frozen contract allows runtime images to
publish these schemas without shipping YAML tooling; handler tests exercise the
actual responses, authorization, preconditions and secret exclusions.

Run `uv run python -m pytest`. Optional real-service verification in
`tests/integration/test_webhook_postgres.py` uses **disposable**
`DUTH62_TEST_DATABASE_URL`, `DUTH62_TEST_RABBITMQ_URL` and
`DUTH62_TEST_RECEIVER_IP`. Migrate that isolated database first. The receiver IP
must be a bindable, non-loopback private interface on the test host. These tests
check concurrent ETags/quota/redelivery, database tenant FKs, four active leases,
and real broker fanout through signed HTTP to a local receiver. They never use a
shared or production database.

The expand-only migration is reversible by downgrading to `d126a001`. Stop the
webhook worker and deploy the old application before downgrading: downgrade
removes webhook configuration, secrets and delivery history. Forward rollback can
instead stop the worker while retaining that data.
