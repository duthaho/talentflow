# TalentFlow documentation

Start with the [project README](../README.md) for what TalentFlow is, the quick start and the pattern catalog.

## Design

| Document | Purpose |
| --- | --- |
| [architecture.md](architecture.md) | Current and target architecture: C4 context and container views, bounded contexts, workflow, event flow, identity flow |
| [events/operations.md](events/operations.md) | Relay, inbox, retry/DLQ operations, replay and verification |
| [events/asyncapi.yaml](events/asyncapi.yaml) | Integration event catalog (AsyncAPI 3.1): envelope, event types, RabbitMQ topology |
| [webhooks/openapi.yaml](webhooks/openapi.yaml) | Outbound webhook contract (OpenAPI 3.1): tenant-admin API and the signed outbound request |
| [roadmap.md](roadmap.md) | The nine DUTH-43 stages: outcome, issues and the patterns each one teaches |

## Architecture decision records

| ADR | Decision | Status |
| --- | --- | --- |
| [001](adr/001-modular-monolith-clean-architecture.md) | Modular monolith with Clean/Hexagonal layering | Accepted |
| [002](adr/002-transactional-outbox.md) | Transactional outbox and at-least-once delivery | Accepted |
| [003](adr/003-local-open-source-runtime-stack.md) | Local open-source runtime stack | Accepted |
| [004](adr/004-web-bff-session-and-typed-client.md) | Web app as a BFF with a server-side session and a generated API client | Accepted |
| [005](adr/005-idempotency-keys.md) | PostgreSQL reservations and safe POST retries | Accepted |
| [006](adr/006-integration-event-contract.md) | Integration event contract: CloudEvents envelope, catalog, RabbitMQ topology, evolution and PII rules | Accepted |
| [007](adr/007-conditional-requests.md) | Aggregate version preconditions over HTTP (ETag / If-Match) | Accepted |
| [008](adr/008-outbound-webhooks.md) | Outbound webhooks: admin API, Standard Webhooks signing, encrypted secrets, SSRF-safe egress, delivery lifecycle | Accepted |

New ADRs use the next number (009), the same header fields (status, date, issue) and sections (context, decision, consequences, rejected alternatives, revisit when). An ADR that is replaced gets the status `Superseded by ADR NNN` and is otherwise left unchanged.

## Runbooks

Browser test setup and acceptance scenarios: [Hiring E2E tests](testing-e2e.md).

| Runbook | Purpose |
| --- | --- |
| [runbooks/backup-restore.md](runbooks/backup-restore.md) | Back up and restore PostgreSQL and attachments in the Compose stack |
| [runbooks/agent-browser.md](runbooks/agent-browser.md) | Recover headless browser automation with Snap Chromium on the QA runner |

## Planned documents

Added by the issues that introduce them: `docs/api-errors.md` (DUTH-46), `docs/performance/` (DUTH-76), `docs/security/threat-model.md` (DUTH-78).

- [Webhook operations](webhooks/operations.md): local receiver, verification, keys, retries and redelivery.
