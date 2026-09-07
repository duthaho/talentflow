# TalentFlow Architecture

## Style

TalentFlow is a **modular monolith** organized by bounded context. A module exposes HTTP adapters, application use cases, domain rules, and infrastructure adapters. Modules communicate through application contracts or versioned integration events, never through another module's persistence records.

```text
HTTP adapter -> application command/query -> domain -> port -> infrastructure adapter
```

## Dependency rule

- `domain`: Python-only business rules; no FastAPI, SQLAlchemy, Pydantic, or provider SDK imports.
- `application`: coordinates a use case through ports/protocols; no HTTP concerns.
- `infrastructure`: SQLAlchemy, SendGrid, and worker implementations.
- `presentation`: request validation, authentication context, and mapping errors to HTTP.

## Candidate transition flow

`TransitionCandidateHandler` receives a command, loads `CandidateCase` through `CandidateRepository`, delegates the transition to the domain aggregate, and applies a version-guarded persistence update. The HTTP layer maps not-found/concurrency errors and records the audit event in the same transaction.

## Reliability

State and `OutboxEvent` must be committed together. Publishers and delivery workers are at-least-once, so stable event IDs and database uniqueness constraints make downstream effects idempotent. This follows the [AWS transactional outbox guidance](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html).

## Extraction criteria

Notifications can become a service when they need independent deployment, throughput, ownership, or availability objectives. The Candidate and Offer modules remain in-process until their bounded contexts and integration contracts are stable.
