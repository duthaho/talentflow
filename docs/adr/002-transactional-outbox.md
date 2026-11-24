# ADR 002: Transactional outbox and at-least-once delivery

- **Status:** Accepted
- **Date:** 2026-11-24
- **Issue:** DUTH-44 (parent DUTH-43)

## Context

A state change often has to trigger work outside its transaction: an email when an offer is approved today; webhooks, the search projection, the onboarding saga and notifications once RabbitMQ arrives in stage 5. Writing the state and then calling the provider or broker loses the side effect if the process dies in between. Calling first sends a message for a transaction that may still roll back. PostgreSQL cannot commit a row and an SMTP send or a broker publish atomically, and two-phase commit is out of place in a modular monolith (ADR 001).

## Decision

A command writes, in **one database transaction**:

1. the aggregate state (for example the offer and candidate workflow state);
2. the business record (for example the immutable approval decision);
3. a versioned event in `outbox_events` (for example `offer.approval_recorded.v1`); and
4. the audit record, when the command is audited.

Work outside the transaction is driven from the outbox and is **at-least-once**. Every reader of the outbox is idempotent on the event id.

**Today.** `app/modules/notifications/application/outbox_publisher.py` materializes pending events into `notification_deliveries`, where `outbox_event_id` is unique, so a replay cannot create a second delivery. `app/modules/notifications/application/delivery_worker.py` leases deliveries, retries failed sends and moves a job to dead letter after the maximum attempts; an expired lease is reclaimed and only the lease holder can finalize. Email goes to SMTP (Mailpit locally) from stage 2 (DUTH-48); SendGrid stays an optional adapter.

**Stage 5 (DUTH-58, DUTH-59).** An outbox relay publishes events to a RabbitMQ topic exchange with publisher confirms and marks them sent only after the confirm. Each consumer writes `(consumer, event_id)` to an inbox table in the same transaction as its side effect, so a redelivered message is applied once. Failed messages retry with delay and end in a dead-letter queue. The event envelope, catalog and topology are fixed by DUTH-58 in its own ADR and `docs/events/asyncapi.yaml`.

Event names carry a version suffix (`.v1`). A change that is not backward compatible publishes a new version alongside the old one until consumers move.

## Consequences

- The intent to notify, publish or project is never lost after a committed business transaction.
- Side effects can happen more than once; adapters and consumers must be idempotent (unique delivery keys, inbox dedup, provider idempotency keys where offered).
- Operations must watch retries and dead letters (Prometheus counters in `app/shared/observability.py` today, Grafana dashboards from stage 2) and, from stage 5, relay lag.
- Payloads carry identifiers, not free-text PII, so events can be logged, replayed and dead-lettered safely.

## Rejected alternatives

- **Publish directly from the request handler.** Loses or invents events around crashes and rollbacks.
- **Change data capture (Debezium on the PostgreSQL WAL).** Removes the polling relay, but adds Kafka Connect and couples consumers to table shapes instead of explicit event contracts.
- **Exactly-once delivery.** Not achievable across a broker and external providers; idempotent consumers give an exactly-once *effect* instead.

## References

- Chris Richardson, *Pattern: Transactional outbox*: <https://microservices.io/patterns/data/transactional-outbox.html>
- [Architecture §7: event flow](../architecture.md#7-event-flow)
