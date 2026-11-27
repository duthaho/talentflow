# RabbitMQ delivery operations (DUTH-59)

ADR [006](../adr/006-integration-event-contract.md) and [AsyncAPI](asyncapi.yaml) define the contract. Candidate creation and all candidate stage transitions (including the offer flow), interview scheduling/feedback, offer creation and approval decisions now write catalog events in the business transaction. `app/shared/events.py` is the persistence-adapter helper: it joins the caller's session and never commits. Domain/application code stays framework-free.

## Local runtime

`docker compose up --build --wait` starts RabbitMQ, the outbox relay and notification consumer/email worker. Retention remains an optional worker profile. The relay is the only worker that scans pending `outbox_events`; the notification consumer verifies a single received event against its tenant-scoped source row; notifications consume `notifications.events` with manual acknowledgement and write the inbox and notification delivery atomically. The existing email worker retries external email separately; an email cannot be exactly once across SMTP and a database. Its delivery ID remains stable across retries.

Configuration names: `RABBITMQ_URL` (secret AMQP URL, including percent-encoded vhost), `OUTBOX_BATCH_SIZE` (1–1000, default 100), `RABBITMQ_PORT`, `RABBITMQ_MANAGEMENT_PORT`, and the existing `WORKER_POLL_SECONDS`, `WORKER_MAX_BACKOFF_SECONDS`, `WORKER_SHUTDOWN_GRACE_SECONDS`. Compose's local development broker credentials are deliberately public and must not be reused elsewhere. The URL is excluded from settings representations. Compose caps idle backoff at five seconds for each messaging worker so the two-hop path fits the existing 30-second email verification budget.

The RabbitMQ management UI is at `http://localhost:15672` by default (local demo user/password `talentflow`). The application declares durable exchanges and quorum queues idempotently. Only the notifications topology is created now; later consumers pass their name/bindings to the shared transport when introduced. Unbound event types are retained in `talentflow.unrouted` until a consumer is deployed; adding a binding does not move those older messages automatically.

The relay uses bounded `FOR UPDATE SKIP LOCKED` batches and persistent messages with publisher confirms. It commits published state only after confirms. A crash before DB commit replays the same IDs. Error bookkeeping stores exception class names only. Shutdown stops before the next event and commits confirmed work; a forced stop rolls back the open batch. No published outbox rows are pruned because delivery rows still reference them.

## Retries, dead letters and replay

Transient consumer failures roll back the inbox and effect, publish the unchanged message to the confirmed retry route, then acknowledge the original. Delays are 10s, 60s and 600s; failure on the fourth processing attempt goes to `notifications.dlq` with `x-tf-failure=exhausted`. Invalid envelopes/types are poison and go directly to DLQ (`poison`), as required by ADR 006. Broker redeliveries are additionally bounded by quorum delivery-limit 10. All dead-letter paths use at-least-once dead-lettering. A republish failure leaves the original unacknowledged/requeued.

1. Inspect `notifications.dlq` in the management UI, including `x-tf-failure`, `x-tf-attempt`, `x-tf-error` (class only), event ID and tenant ID. Avoid copying message bodies into public logs.
2. Fix the consumer/data issue first. Never replay poison automatically. Preserve the CloudEvents body, `id`, AMQP message ID and persistent delivery mode.
3. For an event younger than 30 days, publish that same body to the default exchange (`""`), routing key `notifications.events`, clearing the failure headers and setting `x-tf-attempt=0`. Wait for the broker confirm before acknowledging/removing the DLQ original. If the management UI is used manually, verify that the republished message reached the target queue before deleting its original. A duplicate is safe; deleting the original first can lose it.
4. Events older than 30 days require a controlled rebuild/reconciliation, not DLQ replay. Inbox entries are pruned after 30 days by the notification consumer; existing delivery uniqueness is also retained.
5. For `talentflow.unrouted`, deploy the intended binding, then replay only the appropriate catalog types to that consumer's queue with the same IDs. Replaying to the shared topic exchange also redelivers to existing subscribers, so direct consumer routing is preferable.

## Metrics and dashboard

Worker probes expose `/health/live`, `/health/ready`, `/metrics` on relay port 8001 and notification port 8002 inside Compose. The Collector scrapes both workers into Grafana. The TalentFlow messaging dashboard includes queue depth (`talentflow_broker_queue_depth`, including DLQ and unrouted) and consumer outcomes (`talentflow_consumer_messages_total`: applied, duplicate, skipped_enum, retry, poison, exhausted). Depth is ready messages, excluding in-flight deliveries. Inspect RabbitMQ management for in-flight or retry queue details. The pre-existing `talentflow_outbox_backlog` metric reports unpublished events.

## Verification and migration

`uv run --python 3.13 python -m pytest` runs producer schema/PII/transaction tests and fake-transport failure tests. Set `DUTH59_TEST_RABBITMQ_URL` to a **disposable vhost** to include the real-broker regression: a child relay is SIGKILLed immediately after publisher confirm; restart delivers all events, and inbox processing produces exactly one delivery per event. CI provisions its own broker for this test. The test also verifies actual poison DLQ routing, its depth metric, mandatory-return handling and the existing delivery worker. Set `DUTH59_TEST_POSTGRES_URL` to a disposable, migrated PostgreSQL database to run the concurrent inbox-claim and relay row-lock checks. The pre-existing PostgreSQL integration tests use `DATABASE_URL`; CI enables both settings against its isolated test database.

Migration `d59a001` expands the existing outbox, backfills `occurred_at`, and adds the inbox. Existing rows keep their payload and ID; the relay derives legacy subject/time/correlation defaults. New metadata remains nullable for expand/contract compatibility. Upgrade/downgrade must run only against local/disposable databases. Downgrade removes metadata/inbox but preserves existing outbox and deliveries. Stop relay/consumer before rolling back code and migration; older code can still materialize pending approval events, but it cannot process the newly introduced event types, so rollback requires type-filtering or rolling forward. Do not enable the old unfiltered publisher against a mixed catalog.

Dependencies: `pika` provides synchronous AMQP confirms/manual acknowledgements to fit the existing worker loop; `jsonschema` and explicit `pyyaml` are development dependencies for validating produced envelopes against the catalog.
