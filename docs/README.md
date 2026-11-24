# TalentFlow documentation

Start with the [project README](../README.md) for what TalentFlow is, the quick start and the pattern catalog.

## Design

| Document | Purpose |
| --- | --- |
| [architecture.md](architecture.md) | Current and target architecture: C4 context and container views, bounded contexts, workflow, event flow, identity flow |
| [roadmap.md](roadmap.md) | The nine DUTH-43 stages: outcome, issues and the patterns each one teaches |

## Architecture decision records

| ADR | Decision | Status |
| --- | --- | --- |
| [001](adr/001-modular-monolith-clean-architecture.md) | Modular monolith with Clean/Hexagonal layering | Accepted |
| [002](adr/002-transactional-outbox.md) | Transactional outbox and at-least-once delivery | Accepted |
| [003](adr/003-production-operating-model.md) | Provider-neutral production operating model | Superseded by 005 |
| [004](adr/004-select-aws-sentry-datadog-pagerduty.md) | AWS ECS Fargate, Sentry, Datadog, PagerDuty | Superseded by 005 |
| [005](adr/005-local-open-source-runtime-stack.md) | Local open-source runtime stack | Accepted |

New ADRs use the next number, the same header fields (status, date) and sections (context, decision, consequences, rejected alternatives). A superseded ADR is not edited beyond its status line.

## Runbooks

| Runbook | Purpose |
| --- | --- |
| [runbooks/backup-restore.md](runbooks/backup-restore.md) | Back up and restore PostgreSQL and attachments in the Compose stack |

## Archive

[archive/](archive/README.md) holds the retired AWS production-track documents and explains the status of `infra/opentofu/`.

## Planned documents

Added by the issues that introduce them: `docs/api-errors.md` (DUTH-46), `docs/events/asyncapi.yaml` (DUTH-58), `docs/performance/` (DUTH-76), `docs/security/threat-model.md` (DUTH-78).
