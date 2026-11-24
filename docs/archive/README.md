# Archive

Documents from the retired AWS production track. DUTH-43 made the target runtime local-only (Docker Compose, open-source services), so these are kept for history and are not maintained. Current decisions: [ADR 005](../adr/005-local-open-source-runtime-stack.md) and the [roadmap](../roadmap.md).

| Document | What it was |
| --- | --- |
| [production-infrastructure-roadmap.md](production-infrastructure-roadmap.md) | Phased plan to operate TalentFlow on AWS with Sentry, Datadog and PagerDuty; replaced by [docs/roadmap.md](../roadmap.md). |
| [operations/phase-0-foundation.md](operations/phase-0-foundation.md) | Decision register, environment isolation, launch SLO hypotheses and severity policy for the AWS launch. |
| [operations/incident-management.md](operations/incident-management.md) | Production incident policy built on PagerDuty paging. |
| [runbooks/deployment.md](runbooks/deployment.md) | Image promotion and rollout runbook for a managed container platform. |
| [ADR 003](../adr/003-production-operating-model.md), [ADR 004](../adr/004-select-aws-sentry-datadog-pagerduty.md) | Operating model and AWS/Sentry/Datadog/PagerDuty selection; status `Superseded by ADR 005`, left in `docs/adr/` to keep ADR numbering intact. |

## `infra/opentofu/`

The OpenTofu AWS foundation in [`infra/opentofu/`](../../infra/opentofu/README.md) and its `Infrastructure` CI workflow are **archived and out of scope**. They are not deleted yet (DUTH-44 is docs-only); removing them needs its own issue. Nothing in the local stack depends on them.
