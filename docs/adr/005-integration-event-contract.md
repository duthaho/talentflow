# ADR 005: Integration event contract — envelope, catalog and RabbitMQ topology

- **Status:** Accepted
- **Date:** 2026-11-26
- **Issue:** DUTH-58 (parent DUTH-43)

## Context

ADR 002 commits every state change and its event to the same transaction through `outbox_events`, and defers the broker contract to this ADR. Stage 5 publishes those events to RabbitMQ (DUTH-59). Later stages consume them: webhooks (DUTH-62), the onboarding process manager (DUTH-64), the OpenSearch projection (DUTH-66), and the AI pipeline (DUTH-72). Each consumer is written by a different issue at a different time, so the contract has to be fixed first and be checkable by a machine:

- what every message looks like, whatever its type;
- which events exist, who owns them and when they start flowing;
- how messages are routed, retried and dead-lettered;
- what delivery guarantee a consumer can rely on, and how a schema may change without breaking it;
- what data may travel through a broker that cannot erase what it has already delivered.

Today only one event is written: `offer.approval_recorded.v1` with `{offer_id, decision, actor_id}`, from `app/modules/offers/infrastructure/sqlalchemy_repository.py`. Interviews and candidate stage changes write audit rows, not outbox events; notifications consume the outbox but produce no events.

The machine-readable contract is [`docs/events/asyncapi.yaml`](../events/asyncapi.yaml) (AsyncAPI 3.1). This ADR gives the reasons.

## Decision

### 1. Envelope: CloudEvents 1.0, structured JSON mode

Each message body is one CloudEvents 1.0 event, `content-type: application/cloudevents+json`:

| Attribute | Required | Value |
| --- | --- | --- |
| `specversion` | yes | `"1.0"` |
| `id` | yes | UUID, equal to `outbox_events.id`. Stable across retries and redeliveries; the dedup key. |
| `source` | yes | `urn:talentflow:<context>`, the bounded context that owns the aggregate (fixed per type, so the relay derives it). |
| `type` | yes | `<aggregate>.<past_tense_fact>.v<major>`; also the routing key. |
| `time` | yes | When the fact happened (the command's transaction time), not when it was published. |
| `datacontenttype` | yes | `application/json` |
| `subject` | yes | Id of the aggregate the event is about. |
| `tenantid` | yes | Tenant id. Every consumer scopes its writes by it. |
| `correlationid` | yes | `X-Correlation-Id` of the originating request (`app/shared/observability.py` pattern `[A-Za-z0-9._-]{1,128}`), copied unchanged down the causal chain. |
| `causationid` | yes | Id of the message that directly caused this one: the request's correlation id for API commands, the consumed event's `id` for events emitted by a consumer (saga). |
| `actorid` | no | User id that caused the event; absent for system jobs (retention). |
| `traceparent` | no | W3C trace context (CloudEvents distributed-tracing extension), so a trace spans API → relay → consumer. |
| `data` | yes | The event payload, schema per type. |

The relay also sets the AMQP properties `message_id = id`, `type = type`, `correlation_id = correlationid`, `timestamp`, `app_id = talentflow`, `delivery_mode = 2` (persistent), so the RabbitMQ management UI and tooling show them without parsing the body.

### 2. Naming and versioning

- `type` = `<aggregate>.<past_tense_fact>.v<major>`, lower snake case: `candidate_case.stage_changed.v1`. The aggregate segment is the aggregate type, not the HTTP path. This keeps the type already in the outbox (`offer.approval_recorded.v1`) valid, so no stored row is rewritten.
- The **routing key equals `type`**. Consumers bind by exact type or with topic wildcards (`candidate_case.*.v1`, `*.*.v1`).
- Only the major version is in the name. Minor, additive changes do not change the type.
- Events state facts that happened. Commands are not sent over the bus.

### 3. Catalog

`candidate_case.stage_changed.v1` covers **every** transition in `app/modules/workflow/domain/candidate_state_machine.py`, whichever handler performs it:

| From → to | Written by |
| --- | --- |
| `applied` → `screening` / `rejected` / `withdrawn` | `TransitionCandidateHandler` |
| `screening` → `interviewing` / `rejected` / `withdrawn` | `TransitionCandidateHandler` |
| `interviewing` → `rejected` / `withdrawn` | `TransitionCandidateHandler` |
| `interviewing` → `offer_pending_approval` | `CreateOfferHandler` (`offer_id` set) |
| `offer_pending_approval` → `offer_approved` / `offer_rejected` | `DecideOfferHandler` on the final step (`offer_id` set) |
| `offer_pending_approval` → `withdrawn` | `TransitionCandidateHandler` |
| `offer_approved` → `hired` / `withdrawn` | `TransitionCandidateHandler` |
| `offer_rejected` → `rejected` / `withdrawn` | `TransitionCandidateHandler` |

Full catalog. *Status:* `active` = in the outbox today; `planned` = DUTH-59 starts writing it; `reserved` = name and schema fixed now, first written by the issue named.

| Type | Context | `data` | Status, first publisher | Webhook |
| --- | --- | --- | --- | --- |
| `candidate_case.created.v1` | candidates | `candidate_case_id`, `requisition_id`, `stage`, `channel` (`recruiter` \| `careers_site`), `version` | planned, DUTH-59 (`careers_site` from DUTH-63) | yes |
| `candidate_case.stage_changed.v1` | candidates | `candidate_case_id`, `from_stage`, `to_stage`, `version`, `offer_id?` | planned, DUTH-59 | yes |
| `candidate_case.erased.v1` | candidates | `candidate_case_id`, `reason` (`retention_expired` \| `data_subject_request`) | reserved, DUTH-66 (must exist before the projection holds data) | yes |
| `interview.scheduled.v1` | interviews | `interview_id`, `candidate_case_id`, `interviewer_id`, `scheduled_at` | planned, DUTH-59 | yes |
| `interview.feedback_submitted.v1` | interviews | `interview_id`, `candidate_case_id`, `interviewer_id` | planned, DUTH-59 | no |
| `offer.created.v1` | offers | `offer_id`, `candidate_case_id`, `offer_status`, `approval_step`, `version` | planned, DUTH-59 | yes |
| `offer.approval_recorded.v1` | offers | required: `offer_id`, `decision`, `actor_id`; added optional: `candidate_case_id`, `approval_step`, `offer_status`, `version` | **active**; relayed by DUTH-59 | no |
| `attachment.uploaded.v1` | attachments | `attachment_id`, `candidate_case_id`, `document_type`, `content_type` | reserved, DUTH-72 | no |

- `onboarding.*` is reserved for the DUTH-64 process manager; its spec adds those types here.
- The candidate stage events are emitted inside the transaction that writes the stage. The offer flow already transitions the candidate in its own transaction, so it writes `candidate_case.stage_changed.v1` too, with `source = urn:talentflow:candidates` because the candidates context owns the aggregate.
- `webhook: false` events stay internal: approval chains and feedback timing are internal process data that tenants have not asked to export.

### 4. Delivery: at least once, inbox dedup, no ordering

- **Producer side (DUTH-59).** The relay reads pending `outbox_events` with `FOR UPDATE SKIP LOCKED`, publishes with **publisher confirms**, and marks a row published only after the broker acks. A crash between ack and commit republishes the same `id`. That duplicate is expected.
- **Consumer side.** Each consumer, in **one database transaction**: inserts `(consumer, event_id)` into `inbox_messages`; if the row already exists, commits and acks without doing anything; otherwise applies its side effect, commits, then acks. Effect: exactly once per consumer, on top of at-least-once delivery.
- When the side effect is outside the database (an HTTP webhook, an email), the inbox cannot make it atomic. The consumer writes a delivery row keyed by `(subscription or recipient, event_id)` instead, and the external call is retried from that row. External receivers deduplicate on the CloudEvents `id`, which DUTH-62 sends as the `webhook-id` header.
- **Ordering is not guaranteed.** Retries and parallel consumers reorder messages. Events that describe aggregate state carry `version` (the optimistic-lock version after the change), and consumers that keep state ignore an event whose `version` is not newer than what they hold.

Inbox schema (DUTH-59 migration):

```sql
CREATE TABLE inbox_messages (
  consumer     varchar(64)  NOT NULL,
  event_id     varchar(36)  NOT NULL,
  event_type   varchar(160) NOT NULL,
  tenant_id    varchar(36)  NOT NULL,
  processed_at timestamptz  NOT NULL DEFAULT now(),
  PRIMARY KEY (consumer, event_id)
);
```

Inbox rows are pruned after 30 days. That is far longer than the longest retry path (about 11 minutes, below) and an operator's DLQ replay window. A replay older than that must go through the projection rebuild, not the DLQ.

### 5. RabbitMQ topology

Everything lives in vhost `/talentflow` and is declared by the application at startup (idempotent declarations, DUTH-59).

| Object | Kind | Arguments |
| --- | --- | --- |
| `talentflow.events` | topic exchange, durable | `alternate-exchange = talentflow.unrouted` |
| `talentflow.unrouted` | fanout exchange → quorum queue `talentflow.unrouted` | Catches events with no binding, so nothing is dropped silently. Alert when it is not empty. |
| `talentflow.retry` | direct exchange, durable | — |
| `talentflow.dead-letter` | direct exchange, durable | — |
| `<c>.events` | quorum queue, bound to `talentflow.events` | `x-dead-letter-exchange = talentflow.dead-letter`, `x-dead-letter-routing-key = <c>`, `x-delivery-limit = 10`, `x-dead-letter-strategy = at-least-once`, `x-overflow = reject-publish` |
| `<c>.retry.1` / `.2` / `.3` | quorum queues, bound to `talentflow.retry` with key `<c>.retry.N` | `x-message-ttl` = 10 s / 60 s / 600 s, `x-dead-letter-exchange = ""`, `x-dead-letter-routing-key = <c>.events` |
| `<c>.dlq` | quorum queue, bound to `talentflow.dead-letter` with key `<c>` | No TTL. Replayed by an operator (runbook from DUTH-59). |

Consumers and their binding keys (`<c>`):

| Consumer | Binding keys on `talentflow.events` | Issue |
| --- | --- | --- |
| `notifications` | `offer.approval_recorded.v1` | DUTH-59 |
| `webhooks` | each type whose catalog entry has `webhook: yes` | DUTH-62 |
| `search` | `candidate_case.*.v1`, `interview.*.v1`, `offer.*.v1` | DUTH-66 |
| `onboarding` | `candidate_case.stage_changed.v1`, `candidate_case.erased.v1` | DUTH-64 |

Consumer failure handling (prefetch 10, manual ack):

1. **Poison** — the body is not a valid envelope, or the type or major version is unknown: publish to `talentflow.dead-letter` with header `x-tf-failure = poison`, then ack. It is never retried.
2. **Transient failure** — roll back, read header `x-tf-attempt` (default 0), and republish the unchanged body to `talentflow.retry` with key `<c>.retry.<attempt+1>` and `x-tf-attempt + 1`, waiting for the confirm, then ack. After attempt 3 fails, publish to `talentflow.dead-letter` with `x-tf-failure = exhausted` and the last error class (never the message text, which can echo data).
3. **Crash loop** — a consumer that dies before acking returns the message to the queue. The quorum `x-delivery-limit` dead-letters it after 10 deliveries, so one message cannot stall the queue forever.

Republishing before acking keeps at-least-once semantics through retries. A duplicate is possible and the inbox absorbs it.

### 6. Schema evolution

1. **Within a major version, additive only.** A producer may add an optional `data` field or a new enum value. It may not remove or rename a field, change its type, units or meaning, or make an optional field required.
2. **Tolerant reader.** Consumers ignore unknown fields and treat unknown enum values as "skip and log", not as an error. Producers validate against the strict schema in their tests, consumers do not reject on schema.
3. **Breaking change → new major.** The producer writes both `X.v1` and `X.v2` outbox rows, each with its own `id`, in the same transaction until every binding has moved. Then `X.v1` is marked `deprecated: true` in AsyncAPI and removed no earlier than the next stage. A consumer that binds both versions deduplicates on the business key, not the event id.
4. **Envelope** attributes follow CloudEvents rules: new extension attributes may be added as optional; `specversion` changes only with CloudEvents.
5. **CI gate.** `asyncapi validate docs/events/asyncapi.yaml` (pinned `@asyncapi/cli`) and `tests/unit/test_event_catalog.py` run on every PR. The test fails when the code writes an outbox type that is not in the catalog, when a payload field could hold free text, or when the stage enum drifts from the state machine. DUTH-59 adds producer tests that validate each event it writes against these schemas.

`offer.approval_recorded.v1` is the first application of rule 1: the three fields stored today stay required, and DUTH-59 adds `candidate_case_id`, `approval_step`, `offer_status` and `version` as optional fields, so rows already in the outbox remain valid v1 events.

### 7. No free-text PII in payloads

Payloads carry **only** opaque ids, enums, integers and timestamps. Never names, email addresses, phone numbers, filenames, salaries, interview scores or comments, or rejection reasons. A consumer that needs such data calls the API, which applies tenant RBAC at read time.

Why:

- **A broker cannot erase.** Once delivered, a message may sit in a DLQ, a retry queue, a webhook receiver's log or a search index. Retention purge, DSAR (DUTH-69) and crypto-shredding (DUTH-68) can only reach data held in PostgreSQL. If events carry only ids, destroying the candidate's data or keys leaves the events meaningless rather than leaking.
- **RBAC stays in one place.** Feedback scores, salaries and approval reasons are visible to some roles only. A payload copy would hand them to every consumer and every webhook subscriber, bypassing those rules.
- **Safe operations.** Events are logged, dead-lettered, inspected in the management UI and replayed. Ids make that safe by default.

Ids are still personal data under GDPR, because they are pseudonymous, not anonymous. The rule minimizes data and keeps it erasable; it does not make events anonymous. `ActorId` and `TraceId` are pattern-restricted so that an email address cannot pass as an id. `tests/unit/test_event_catalog.py` enforces that every string field in `data` has a format, enum or pattern.

## Implementation and rollout (DUTH-59)

1. **Expand** `outbox_events` (Alembic): `occurred_at timestamptz` (backfilled from `created_at`), `subject`, `correlation_id`, `causation_id`, `actor_id`, `traceparent`, `publish_attempts int default 0`, `last_error text`. The `topic` column keeps holding `type`. Add `inbox_messages`. New columns are nullable at first, so the old code still runs.
2. Command handlers write the planned events with the new columns. The relay builds the envelope; for legacy rows it uses `created_at` as `time`, `offer_id` as `subject` and `correlationid = causationid = id`.
3. Add RabbitMQ to Compose, declare the topology, start the relay. Switch notifications from the in-process `OutboxPublisher` to the `notifications` consumer. That consumer keeps writing `notification_deliveries`, whose unique `outbox_event_id` already acts as its inbox. The relay is now the only reader of `outbox_events`.
4. **Contract**: remove the in-process publisher and make the expanded columns `NOT NULL` once no legacy pending rows remain.

Rollback before step 4: stop the relay and re-enable the in-process publisher. Pending rows are untouched because only a broker ack marks them published.

## Consequences

- Each later issue (DUTH-59, 62, 64, 66, 72) codes against a fixed, validated contract instead of agreeing on one in review.
- Consumers must be idempotent and order-tolerant. That cost is now explicit and shared (inbox, `version`).
- Consumers make extra API reads because payloads are thin. Those reads go through RBAC, which is the point. The search projector reads in batches.
- Four retry and dead-letter queues per consumer is more topology to operate. In exchange, retry timing is visible in the management UI and needs no plugin.
- `notification_deliveries.outbox_event_id` has an `ON DELETE CASCADE` foreign key to `outbox_events`. DUTH-59 must not prune published outbox rows until that dependency is removed.

## Rejected alternatives

- **Custom envelope (snake_case `event_id`, `occurred_at`, ...).** Equally expressive, but webhook receivers, AsyncAPI tooling and tracing would each need a TalentFlow-specific mapping. CloudEvents has an AMQP binding and a webhook spec, which DUTH-62 reuses.
- **CloudEvents binary mode (attributes in AMQP headers).** The body would be the payload alone, so a message copied from a DLQ, a log or a webhook body would lose its metadata. Structured mode keeps every copy self-describing.
- **Fat events (full candidate or offer state in `data`).** Fewer API reads, but PII and role-restricted fields would spread into stores that cannot be erased or authorized (§7).
- **One type per target stage (`candidate_case.hired.v1`, ...).** Gives routing by outcome, but adds nine types for one fact, and each new stage would be a contract change. The onboarding consumer filters `to_stage = hired` after its inbox insert, which is cheap at this volume.
- **Broker-only retry (`nack` + DLX with a single TTL).** Only one delay is possible, and `x-death` grows on every hop. Tiered retry queues with an explicit attempt header are easier to read and tune.
- **`rabbitmq_delayed_message_exchange` plugin.** Not in the official image (ADR 003 requires official images), and its delayed messages are not replicated.
- **Global or per-aggregate ordering (single active consumer, consistent-hash exchange).** Serializes throughput and still breaks under retries. Version checks give the same correctness more cheaply.

## Revisit when

- A consumer needs replay beyond 30 days or a high-volume stream. Consider RabbitMQ streams or Kafka (ADR 003 rejected Kafka for now).
- An external partner needs payload data that it cannot fetch through the API. Design a separate, consented export rather than enriching events.

## References

- CloudEvents 1.0 specification and AMQP protocol binding: <https://github.com/cloudevents/spec>
- AsyncAPI 3.1 specification: <https://www.asyncapi.com/docs/reference/specification/v3.1.0>
- RabbitMQ quorum queues (delivery limit, at-least-once dead-lettering): <https://www.rabbitmq.com/docs/quorum-queues>
- [ADR 002: Transactional outbox](002-transactional-outbox.md)
