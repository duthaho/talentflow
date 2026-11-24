# ADR 001: Modular monolith with Clean/Hexagonal layering

- **Status:** Accepted
- **Date:** 2026-11-24
- **Issue:** DUTH-44 (parent DUTH-43)

## Context

TalentFlow is a learning showcase: one runnable application that shows how an enterprise system is designed, built, operated and evolved. It has one team, an evolving domain and a single PostgreSQL database. Separately deployed services would bring distributed tracing, network failure handling, deployment coordination and cross-service consistency before anything shows that independent deployment or scaling is needed. They would also make the codebase harder to read in an afternoon, which is the point of the project.

The roadmap adds a web app, broker-based integration events, a saga, search, feature flags and AI features (stages 2–9). The structure has to absorb these without the business rules depending on FastAPI, SQLAlchemy, RabbitMQ or any vendor SDK.

## Decision

TalentFlow is a **modular monolith**: one deployable API, background workers built from the same image, one PostgreSQL transactional boundary. Each bounded context under `app/modules/<context>/` is split into layers whose dependencies point inward:

- **Domain:** aggregates, state machines, policies, value objects and domain errors. No imports of FastAPI, SQLAlchemy, Pydantic or provider SDKs.
- **Application:** commands, queries, ports and transaction boundaries. Depends on the domain and on ports only.
- **Infrastructure:** SQLAlchemy repositories, outbox persistence and adapters that implement ports (SMTP, S3, ClamAV, OpenBao, RabbitMQ, Ollama…).
- **Presentation:** FastAPI routers and Pydantic DTOs. Maps HTTP to commands and domain/application errors to responses.

Reads use **CQRS-lite**: commands own invariants and transactions; queries may read optimized projections (SQL views now, OpenSearch in stage 7) without event sourcing.

Contexts talk to each other through application ports in-process, and through versioned integration events (outbox, then RabbitMQ in stage 5) when the reaction can be asynchronous.

`tests/architecture/test_dependency_rule.py` enforces the inward rule today. Two gaps remain from the baseline: most routes still live in `app/main.py` and ORM records are shared in `app/shared/models.py`. DUTH-45 (stage 2) moves both into their modules and extends the architecture test to forbid cross-module infrastructure imports.

## Consequences

- Workflow rules are unit-tested without a database or HTTP.
- Frameworks and providers are replaceable adapters; ADR 003 relies on this to keep every runtime service behind a port.
- Module boundaries are checked by tests, not only by folder names.
- One process and one transaction boundary: no distributed transactions, and consistency inside a command is plain ACID.
- The integration events of stage 5 create the seam a future extraction would use.

## Rejected alternatives

- **Microservices from the start.** Operational cost (per-service deploys, network failures, eventual consistency everywhere) with no scaling or team-ownership need to pay for it.
- **Layered monolith without module boundaries** (one `models`, `services`, `routes` package). Simple at first, but nothing stops cross-context coupling, and the extraction seams disappear.

## Revisit when

A module shows evidence that it should be its own service: materially different scaling or availability needs, an independent release cadence or owning team, a hard security boundary, or lower operational cost than in-process integration. The criteria and likely order (Notifications, then read projections, then AI jobs) are in [architecture §12](../architecture.md#12-service-extraction-criteria).
