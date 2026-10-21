# ADR 004: Select AWS ECS Fargate, Sentry, Datadog, and PagerDuty

- **Status:** Accepted
- **Date:** 2026-10-21

## Context

ADR 003 established a vendor-neutral production workload contract while deferring vendor selection. The platform choices are now required to build infrastructure as code, define telemetry integration points, and prepare an audited deployment path without creating a microservice estate.

TalentFlow needs a managed container runtime for an API and bounded workers, managed PostgreSQL/Redis/object storage integrations, GitHub Actions workload identity, application error tracking with PII controls, unified operational telemetry, and an escalation product. The repository contains no vendor credentials and no live account information.

## Decision

1. Use **AWS ECS Fargate** as the initial managed runtime. Staging and production must be isolated in separate AWS accounts. Use managed AWS services: RDS PostgreSQL with PITR, ElastiCache Redis with TLS/authentication, private S3 attachment storage, ECR, Secrets Manager, CloudWatch, Route 53/ACM where AWS owns DNS, and IAM.
2. Use **OpenTofu** for AWS infrastructure. Its state is stored in a private, encrypted, versioned S3 bucket with native S3 lock files. Bootstrap state separately from managed environment state.
3. Use **GitHub Actions OIDC** to assume narrowly scoped AWS roles. Do not store long-lived AWS keys in GitHub or repository configuration.
4. Use **Sentry** for application exception and performance event tracking. Add it only behind an explicit configuration gate with PII/sensitive-data scrubbing and bounded sampling.
5. Use **Datadog** as the initial metrics, logs, traces, dashboards, and alert-routing backend. Continue to emit OpenTelemetry/OTLP so application code is not coupled to Datadog libraries.
6. Use **PagerDuty** for actionable paging. Route deploy, vulnerability, and non-urgent operational notifications to the selected chat integration after its workspace/channel is approved.

## Consequences

- A single platform reduces operational surface for the first production release while retaining application-level OpenTelemetry portability.
- AWS account IDs, region, domain, Datadog site/project, Sentry organization/project, PagerDuty service/escalation policy, chat workspace/channel, pricing limits, and vendor credentials remain deployment-time inputs. They are not inferred, generated, or committed.
- The OpenTofu foundation intentionally creates no RDS, Redis, ECS service, or task definition. Their topology and capacity must be approved with production account, region, availability-zone, DNS, certificate, database, and cost information in the later delivery phase.
- This selection is revisited when measured workload, residency, contract, cost, or availability requirements make the initial design unsuitable.

## Rejected alternatives

- **Kubernetes before workload evidence:** increases cluster, networking, patching, and on-call complexity without a demonstrated need.
- **Self-hosted ELK with Datadog:** duplicates telemetry pipelines and operational ownership.
- **Static AWS credentials in CI:** increases compromise and rotation risk compared with OIDC federation.
- **Application-direct paging:** lacks central deduplication, escalation, auditability, and incident coordination.
