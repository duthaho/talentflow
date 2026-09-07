# ADR-001: Modular Monolith and Clean Architecture

**Status:** Accepted
**Date:** 2026-09-07

## Context

TalentFlow is a multi-tenant HR workflow platform with a single delivery team and an evolving domain. Starting with separately deployed services would impose distributed tracing, network-failure handling, deployment coordination, and cross-service consistency before there is evidence that independent deployment or scaling is needed.

The original implementation already contained useful patterns—state machines, approval policies, audit records, optimistic locking, and a transactional outbox—but HTTP endpoints also owned orchestration and persistence concerns. That organization makes rules harder to test independently and obscures future extraction seams.

## Decision

TalentFlow remains a **modular monolith**. Each bounded context is organized into these dependency directions:

- **Domain:** aggregates, policies, value objects, and domain errors. This layer must not import FastAPI, SQLAlchemy, Pydantic, or delivery-provider SDKs.
- **Application:** commands, query services, ports, orchestration, and transaction boundaries. It depends on domain abstractions only.
- **Infrastructure:** SQLAlchemy repositories, outbox persistence, and provider adapters implementing application ports.
- **Presentation:** FastAPI route adapters and Pydantic request/response DTOs. It maps transport concerns to application commands and maps application/domain errors to HTTP responses.

Commands and queries use CQRS-lite separation: write use cases own invariants and transactions; read paths may use optimized persistence queries without introducing event sourcing.

## Consequences

- Unit tests can exercise workflow rules without database or HTTP setup.
- SQLAlchemy and FastAPI are replaceable implementation details rather than domain dependencies.
- Module boundaries are tested as architectural constraints, not only documented conventions.
- The monolith retains an in-process deployment model and one transactional database boundary.
- Cross-context communication uses versioned outbox event contracts, preserving a future seam for asynchronous extraction.

## Extraction Criteria

A module may be extracted only when evidence supports it: materially different availability or scaling needs, independent release cadence, a dedicated owning team, hard security/isolation requirements, or a bounded context whose operational cost is lower than continued in-process integration. Notifications is the first likely candidate because it already has an outbox boundary and independent delivery worker.
