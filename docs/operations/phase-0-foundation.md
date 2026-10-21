# Phase 0 production foundation

## Purpose

Phase 0 establishes the operating contract and decision gates that must exist before infrastructure provisioning. It does not claim a live deployment. The repository currently proves application behavior and CI checks; the selected platform must produce staging and production evidence later.

## Repository baseline, verified on 2026-10-21

### Implemented application controls

- Production configuration rejects development header authentication, non-PostgreSQL databases, missing Redis, insecure CORS, non-HTTPS OIDC/calendar configuration, relative attachment storage, and disabled malware scanning.
- Alembic migrations are used in production; application startup only creates schema in non-production environments.
- HTTP liveness, readiness, Prometheus metrics, JSON logs with correlation IDs, and FastAPI OpenTelemetry instrumentation are present.
- API rate limiting uses Redis when configured; CI exercises PostgreSQL and Redis.
- Private attachment storage, retention controls, legal holds, bounded retention purge, and transactional notification processing are implemented.
- CI validates formatting, lint, migrations, tests, container startup, readiness, metrics, and a bounded worker command. Security validates CodeQL and critical dependency/image vulnerabilities.

### Gaps deliberately not represented as complete

- No cloud account/project, region, registry, DNS, production secret manager, managed service, or workload identity has been selected or provisioned.
- No Sentry project/DSN, OTLP Collector, metrics/log backend, dashboard, alert route, paging integration, or incident communication channel is configured.
- No staging deployment, production deployment, backup restore drill, rollback drill, OIDC-provider verification, email-provider verification, malware-scanner verification, or load-test result exists.
- Local Docker daemon is unavailable in this development environment. Container behavior is verified by GitHub Actions, not locally.

## Required decision register

The accountable delivery owner must complete every field before provisioning. Values are intentionally blank; do not place credentials, tokens, connection URLs, or DSNs in this document.

| Decision | Required outcome | Accountable role | Evidence required |
| --- | --- | --- | --- |
| Cloud and runtime | One cloud account/project, region, managed container platform, and organization billing owner | Platform owner | Approved architecture/change record |
| Data residency | Jurisdiction, data classification, retention and deletion requirements | Security/privacy owner | Data classification approval |
| Network and DNS | Public API domain, TLS ownership, inbound controls, private dependency paths | Platform owner | Network design and DNS ownership record |
| Database | Managed PostgreSQL version, HA/PITR policy, encryption, backup retention, restore access | Database owner | Service configuration and restore plan |
| Cache | Managed Redis tier, TLS, auth, persistence and eviction policy | Platform owner | Service configuration and capacity policy |
| Object storage | Private bucket/container, encryption, lifecycle, scanner path and deletion access | Security/platform owner | Access policy and lifecycle review |
| Identity | OIDC issuer, audience, claims mapping, key rotation and break-glass procedure | Identity owner | Staging JWT verification record |
| Email | Verified sender, suppression/bounce handling, recipient policy | Product/platform owner | Staging delivery record |
| Observability | Sentry yes/no; one metrics/log/trace backend; retention and cost owner | SRE/platform owner | Vendor selection record |
| Paging and chat | PagerDuty/Opsgenie or provider-native paging; non-page chat destination | Incident manager | Test alert delivery record |
| Delivery | Container registry, signing authority, protected environments and rollout strategy | Release owner | CI/CD design review |

## Environment isolation contract

- Dev, staging, and production use separate accounts/projects or equivalent hard isolation boundaries.
- Production never shares PostgreSQL, Redis, object storage, OIDC client, email sender configuration, or secrets with lower environments.
- Staging uses synthetic, non-PII data. Restored production data requires a documented exception, isolated access, and disabled side-effect workers.
- Secrets come from the selected platform secret manager at runtime. CI uses GitHub OIDC federation where supported; no static cloud credentials are stored in source control.
- Every deployment records source revision, immutable image digest, migration revision, environment, operator/deployment identity, and change reference.

## Initial reliability objectives

These are launch hypotheses, not observed production SLOs. Recalibrate after one full error-budget window of real traffic.

| Indicator | Objective | Measurement window | Initial alert intent |
| --- | --- | --- | --- |
| API availability | 99.9% successful, valid requests | Calendar month | Page on multi-window burn rate |
| Read latency | 99% below 300 ms | 30 days | Investigate trend; page only with availability impact |
| Write latency | 99% below 700 ms | 30 days | Investigate trend; page only with availability impact |
| Server errors | Less than 0.1% of valid API requests | Calendar month | Page on budget burn, not a single spike |
| Outbox backlog age | Below 10 minutes | Continuous | Page when sustained and user-impacting |
| Restore recovery | RPO 24 hours; RTO 4 hours | Quarterly drill | Incident if a drill misses target |

Excluded request classes must be documented in the telemetry query: health checks, expected authorization failures, invalid client input, and intentional rate-limit responses do not count as availability failures. No candidate identifiers, email addresses, feed tokens, or attachment names may become metric labels.

## Severity and ownership policy

- **SEV-1:** confirmed broad production outage, active security incident, or suspected unauthorized access to sensitive data. Page incident commander and platform owner immediately; establish an incident channel and status cadence.
- **SEV-2:** material degradation, sustained SLO burn, delayed customer workflows, dependency failure with a viable workaround, or failed recovery control. Page the service owner; publish a stakeholder update.
- **SEV-3:** limited degradation, failed bounded worker cycle with no current customer impact, elevated errors without burn, or a non-critical security finding. Create a ticket during business hours.
- **SEV-4:** request, observation, or improvement with no current service impact. Track in normal planning.

Every production service and alert must have a named primary owner, backup owner, escalation path, runbook URL, dashboard URL, and last-tested date before launch.

## Phase 0 completion criteria

Phase 0 is complete only when:

1. The decision register is filled and approved by accountable owners.
2. The cloud/runtime, region, identity, telemetry backend, paging route, and deployment strategy are selected.
3. A repository-backed infrastructure design identifies remote-state location, access roles, environments, managed services, network boundaries, registry, and secret injection—not secrets themselves.
4. Initial dashboards, alert ownership, on-call schedule, change policy, and incident communication policy are approved.
5. A production readiness review records the remaining Phase 1–5 acceptance evidence and dates.

Until then, Phase 0 documentation is complete but production infrastructure is not provisioned.
