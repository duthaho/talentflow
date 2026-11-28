# ADR 011: Persisted onboarding process manager

Status: accepted under the approved DUTH-64 plan.

A hire initiates sequential HRIS, directory, task and notification work. The external
systems can fail independently and cannot participate in the recruiting transaction.
We choose orchestration: the onboarding module owns order, retry/deadline policy,
reverse compensation and the task pivot. Choreography would distribute the same
state machine across event handlers and make cancellation, erasure and progress
queries harder to reason about. No new integration events are introduced.

We choose an in-house process manager over Temporal for this bounded, four-step
showcase. Temporal provides durable scheduling, workflow versioning and rich
operational tools, at the cost of another control plane and runtime programming
model. PostgreSQL already provides our durable inbox, unique case identity,
transactions and locks. A due-time index doubles as a work queue; `in_flight`
with a future due time is a recoverable lease. Claim uses a short transaction,
`SKIP LOCKED` and a version compare-and-set. HTTP runs outside the transaction.
Outcome recording is fenced by a unique owner token. Local task/notification
work commits atomically with its outcome. Hired/erased races use a transaction
advisory lock on the tenant/case pair. Cancellation waits for a live attempt;
every attempted external step is treated as potentially effective until its
ownership-checked cleanup succeeds when abandoned. This includes retry-wait
steps after a timeout, regardless of the latest failure class. The persisted
attempt count is sufficient; no extra uncertainty flag or schema is needed.
Cleanup uses stable ownership identity without PII reads and runs in reverse
order. Notify is after the pivot.

This choice makes us responsible for policy, lease recovery and tests. PostgreSQL
concurrency, killed-process recovery against real HRIS/Keycloak, fake-clock
policy tests and the operational runbook are required evidence. Reconsider a
workflow engine if workflows become dynamic, cross-service versions proliferate,
or operational recovery costs outweigh another managed service.

Notification delivery expands compatibly with nullable outbox ids, kind and
unique dedup keys; onboarding publishes no synthetic offer event. Delivery payloads
contain ids/dates/task keys only. Names are resolved at send time, with an anonymous
fallback. Keycloak accounts remain disabled, and deletion/adoption checks the
admin-only saga ownership attribute. Provisioning credentials stay with the worker.

See [onboarding operations](../onboarding.md), [spec/plan](../specs/DUTH-64.md),
and `tests/integration/test_onboarding*.py` for the contract and evidence.
