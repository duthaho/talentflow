# ADR 003: Provider-neutral production operating model

- **Status:** Accepted
- **Date:** 2026-10-21

## Context

TalentFlow is a modular monolith with an API, bounded workers, PostgreSQL, Redis, private attachment storage, OIDC, and external email delivery. The repository contains production guards and CI evidence, but it does not own a cloud account, registry, DNS zone, identity tenant, paging account, or monitoring subscription.

Selecting a cloud provider, Kubernetes distribution, and monitoring vendor before an accountable owner, budget, data residency requirement, and deployment region are known would create speculative infrastructure and credentials. Running Datadog, self-hosted ELK, and multiple deployment targets in the first release would also duplicate operational effort without increasing launch confidence.

## Decision

1. Retain a modular-monolith deployment. Do not extract services as a prerequisite for production launch.
2. Define one portable workload contract: immutable API and worker images; managed PostgreSQL with point-in-time recovery; managed Redis; private object storage; an OIDC identity provider; a secret manager; and an OpenTelemetry Collector endpoint.
3. Use OpenTelemetry as the application telemetry contract. Select exactly one initial observability backend—Datadog or Grafana Cloud—during environment provisioning. Sentry remains a separate error-tracking product if adopted.
4. Use infrastructure as code through Terraform or OpenTofu with encrypted, locked remote state. Provisioning must occur from reviewed code under a dedicated production account/project.
5. Use GitHub Actions OIDC federation for cloud and registry access where the selected platform supports it. Do not store long-lived cloud keys in repository or GitHub secrets.
6. Promote one signed image digest from staging to production. Production deployment requires a protected environment, least-privilege deploy identity, migration job, readiness evidence, and rollback-compatible schema.
7. Treat vendor selection and production provisioning as explicit gates, not completed repository work. No provider, account, credential, DNS name, alert destination, or customer data is committed here.

## Consequences

- Application code can be integrated with Sentry and OTLP later without coupling business modules to a monitoring provider.
- The first production release has one telemetry backend and one deployment target, lowering alerting and cost complexity.
- Environment provisioning cannot begin until the decision record in `docs/operations/phase-0-foundation.md` has accountable owners and approved selections.
- Terraform/OpenTofu modules will be added only after the selected provider, region, data-residency constraints, and organization boundaries are supplied.

## Rejected alternatives

- **Self-host ELK plus Datadog:** duplicate ingestion, alerting, retention, cost, and on-call burden.
- **Commit provider-specific IaC now:** no cloud account, region, or ownership decision exists to validate it.
- **Deploy directly from developer machines:** lacks auditable identity, promotion control, and rollback evidence.
- **Split to microservices first:** adds distributed operational complexity before a production workload demonstrates a need.
