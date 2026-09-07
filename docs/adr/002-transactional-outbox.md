# ADR-002: Transactional Outbox and At-Least-Once Delivery

**Status:** Accepted
**Date:** 2026-09-07

## Context

Offer decisions change workflow state and must produce downstream notification work. Writing state to the database and then publishing directly to an external provider risks lost notifications when the process fails between those operations. Publishing first risks a notification for a transaction that later rolls back.

A database transaction cannot atomically commit local state and an external SendGrid request without distributed transaction coordination, which is not appropriate for this modular monolith.

## Decision

The command that records an offer approval decision persists all of the following in one database transaction:

1. the offer and candidate workflow state;
2. the immutable approval decision;
3. a versioned outbox event (`offer.approval_recorded.v1`); and
4. the associated audit record when applicable.

A background publisher materializes notifications from pending outbox events. Delivery workers may retry. This provides **at-least-once** processing rather than exactly-once delivery.

Consumers and materializers must use durable idempotency keys. `notification_deliveries.outbox_event_id` is unique, so replaying an already materialized outbox event cannot create a duplicate delivery record.

## Consequences

- The system does not lose the intent to notify after a successful business transaction.
- Provider calls are retried asynchronously and may occur more than once; external adapters must be idempotent where supported.
- Operational monitoring must track pending, failed, and dead-letter delivery states.
- Event contracts are versioned and additive changes should use a new topic version when compatibility is not guaranteed.

## References

- [AWS Prescriptive Guidance: Transactional outbox pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)
