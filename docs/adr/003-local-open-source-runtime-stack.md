# ADR 003: Local open-source runtime stack

- **Status:** Accepted
- **Date:** 2026-11-24
- **Issue:** DUTH-44 (parent DUTH-43)

## Context

TalentFlow is a learning showcase: one runnable application that shows how an enterprise system is designed, built, operated and evolved. An earlier plan aimed at an operated AWS production environment (ECS Fargate, RDS, ElastiCache, S3, Sentry, Datadog, PagerDuty). That track needs cloud accounts, budgets and vendor contracts that a showcase does not have, and a reader cannot run it.

On 2026-11-24 the project owner decided (DUTH-43):

1. The target runtime is **local only**: Docker Compose, no cloud provisioning. The AWS/OpenTofu track is out of scope.
2. Every supporting service is **open source** and has an **official (vendor- or project-published) container image**.
3. The stack is **minimal**: a service is added only when a pattern in the [roadmap](../roadmap.md) needs it.

The application code keeps talking to ports and open protocols (OIDC, SQL, S3 API, AMQP 0-9-1, SMTP, OTLP, OpenFeature, Sentry SDK protocol), so a later move to managed cloud services swaps adapters and configuration, not business code.

## Decision

Run the services below in `docker-compose.yml`. Exact image tags are pinned by the compose issue that introduces each service (DUTH-50 for the stage 2 core); this ADR fixes the product, licence and image repository. "Stage" is the [roadmap](../roadmap.md) stage that first needs the service.

### Summary

| Service | Purpose | Licence | Official image | Stage | Rejected alternative |
| --- | --- | --- | --- | --- | --- |
| Keycloak | OIDC identity provider | Apache-2.0 | `quay.io/keycloak/keycloak` | 2 | Authentik, ZITADEL |
| PostgreSQL + pgvector | System of record, vector search | PostgreSQL License (both) | `pgvector/pgvector` (`pg17` tags) | 2 (pgvector used in 8) | Separate vector DB (Qdrant, Weaviate) |
| Redis | Rate-limit counters, short-lived cache | Redis 8: RSALv2 / SSPLv1 / **AGPLv3** (we use it under AGPLv3) | `redis` (Docker Official Image), `8.x` tags | 2 (already used) | Valkey (BSD-3-Clause) |
| RabbitMQ | Integration-event broker, retries, DLQ | MPL-2.0 | `rabbitmq` (Docker Official Image), `4.x-management` tags | 5 | Apache Kafka |
| OpenSearch | Candidate search projection | Apache-2.0 | `opensearchproject/opensearch` | 7 | Elasticsearch |
| SeaweedFS | S3-compatible attachment storage | Apache-2.0 | `chrislusf/seaweedfs` | 2 | MinIO, Garage, RustFS |
| ClamAV | Malware scanning of uploads | GPL-2.0 | `clamav/clamav` | 2 | No scan / commercial AV API |
| Mailpit | SMTP sink with web UI | MIT | `axllent/mailpit` | 2 | MailHog, real SendGrid account |
| OpenBao | Transit encryption, per-tenant keys | MPL-2.0 | `openbao/openbao` | 7 | HashiCorp Vault |
| flagd (OpenFeature) | Feature-flag provider | Apache-2.0 | `ghcr.io/open-feature/flagd` | 6 | Unleash |
| OpenTelemetry Collector | Telemetry pipeline (OTLP in, fan out) | Apache-2.0 | `otel/opentelemetry-collector-contrib` | 2 | Direct export from the app |
| Grafana LGTM | Dashboards, logs, traces, metrics | Image build: Apache-2.0; Grafana, Loki, Tempo: AGPLv3; Prometheus: Apache-2.0 | `grafana/otel-lgtm` | 2 | Separate Grafana/Loki/Tempo/Prometheus containers; Jaeger + Prometheus |
| GlitchTip | Error tracking (Sentry SDK compatible) | MIT | `glitchtip/glitchtip` | 9 | Self-hosted Sentry |
| Ollama | Local LLM and embedding runtime | MIT | `ollama/ollama` | 8 | vLLM, LocalAI, hosted LLM API |

Test tooling from DUTH-43 that does not run as a stack service: **k6** (AGPLv3, `grafana/k6`, stage 9 load tests) and **Playwright** (Apache-2.0, `mcr.microsoft.com/playwright`, stage 4 E2E).

### Per-service rationale

**Keycloak — identity.** The API already validates RS256 JWTs against a JWKS (`app/modules/identity/infrastructure/jwt_validator.py`). Keycloak gives a standards-complete OIDC provider with realm import (repeatable demo users and roles), authorization code + PKCE for the web app, and an admin API the onboarding saga uses to provision accounts (stage 6). It is a CNCF project with the widest documentation base. *Rejected:* Authentik (good UI, but its admin API and realm-as-code story are weaker for scripted seeding) and ZITADEL (strong multi-tenancy, but its tenant model would compete with TalentFlow's own tenant model and it is less familiar to readers).

**PostgreSQL + pgvector — system of record and embeddings.** PostgreSQL is already the system of record. The `pgvector/pgvector` image is PostgreSQL plus the extension, so one database covers relational data, Row-Level Security (stage 7) and semantic matching (stage 8). Embeddings stay inside the tenant-scoped transaction boundary and backups. *Rejected:* a dedicated vector database adds a second store to secure, back up and keep consistent, for a data volume that pgvector handles.

**Redis — rate limits and cache.** Already used by `app/shared/rate_limit.py`. Redis 8 added AGPLv3 as a licence option (May 2025), which is OSI-approved; we run it unmodified as a local service. Note: the current compose file pins `redis:7-alpine`, which resolves to 7.4+ under RSALv2/SSPLv1 only; DUTH-50 moves it to an `8.x` tag. *Rejected for now:* Valkey (BSD-3-Clause, Linux Foundation, wire-compatible with the `redis` Python client). It is the fallback if the AGPL obligations ever matter (e.g. a modified, network-served build); switching is a one-line image change.

**RabbitMQ — integration events.** Stage 5 publishes domain events from the outbox to a broker; consumers need per-message acknowledgement, retry with delay, dead-letter queues and routing by event type. RabbitMQ provides these natively (topic exchanges, quorum queues, DLX, publisher confirms) with a management UI that makes the flow visible to a reader. *Rejected:* Apache Kafka (Apache-2.0). Its strengths — a replayable partitioned log and very high throughput — are not needed here; per-message retry/DLQ must be built by hand, and it is heavier to run locally. Replay for the search projection is covered by rebuilding from PostgreSQL.

**OpenSearch — search projection.** Full-text search with facets over a tenant-isolated, rebuildable read model (stage 7). OpenSearch is Apache-2.0 and governed by the OpenSearch Software Foundation under the Linux Foundation. *Rejected:* Elasticsearch. Since August 2024 its source is available under a choice of AGPLv3, SSPL or the Elastic License 2.0, so it is open source again under AGPLv3; but the default distribution and image bundle Elastic-licensed features, and the licence has changed twice since 2021. OpenSearch gives a single permissive licence with no feature-tier boundary to explain.

**SeaweedFS — S3-compatible object storage.** Attachments move from a local volume to private S3 buckets with presigned downloads (DUTH-49). MinIO, the usual local choice, stopped publishing community images and binaries in October 2025, put the community repository in maintenance mode in December 2025 and has since archived it, so it no longer meets "official image". Current options:

| Option | Licence | Image | Notes |
| --- | --- | --- | --- |
| SeaweedFS | Apache-2.0 | `chrislusf/seaweedfs` | Mature, active; `weed server -s3` runs master, volume, filer and S3 gateway in one container; supports SigV4 and presigned URLs. |
| Garage | AGPLv3 | `dxflrs/garage` | Small single binary, presigned URLs supported; needs a cluster-layout bootstrap step before first use and has no object versioning. |
| RustFS | Apache-2.0 | `rustfs/rustfs` | MinIO-like API and console, but young; stability is still settling. |
| Community MinIO rebuilds | AGPLv3 | third-party (e.g. `pgsty/minio`) | Not official images; rejected by decision 2. |

*Decision:* SeaweedFS — permissive licence, single container for the local case, no manual layout step in `docker compose up`. DUTH-49 must verify presigned GET expiry and private-bucket behaviour against the pinned version; if either fails, Garage is the fallback. The application only depends on the S3 API, so the store is replaceable.

**ClamAV — malware scanning.** Uploads are already scanned through the `MalwareScanner` port (`app/modules/attachments/infrastructure/filesystem_storage.py`, currently by invoking `clamscan`). The official `clamav/clamav` image runs `clamd` with signature updates; the compose stack exposes it so the scanner adapter can call it over the network. *Rejected:* skipping scanning (the CV upload path is untrusted input, especially with public self-apply in stage 5) and commercial scanning APIs (not open source, need accounts).

**Mailpit — email sink.** Local SMTP server with a web UI and API, so the E2E test (stage 4) can assert that an email was sent. *Rejected:* MailHog (unmaintained since 2020) and a real SendGrid account (needs a verified sender and credentials; SendGrid stays as an optional adapter selected by config, DUTH-48).

**OpenBao — encryption keys.** Stage 7 encrypts candidate PII with per-tenant keys and crypto-shredding. OpenBao's transit engine does envelope encryption, key rotation and key deletion without the app ever holding key material. It is the Linux Foundation fork of Vault from before the licence change. *Rejected:* HashiCorp Vault — Business Source License 1.1 since August 2023, not open source.

**flagd — OpenFeature provider.** The API and workers call the vendor-neutral OpenFeature SDK; flagd is the provider (stage 6). The web app does not evaluate flags itself: it reads server-evaluated state from the API ([ADR-010](010-feature-flags.md)). Flags live as JSON in the repo, are reviewed like code, support targeting rules (per tenant, per role) and are hot-reloaded when the file changes, so a toggle needs no redeploy. It is one small stateless container and part of the CNCF OpenFeature project. *Rejected:* Unleash (Apache-2.0 core, `unleashorg/unleash-server`). It has a richer UI and audit trail, but needs its own PostgreSQL database and keeps flag state outside Git. Because the code depends only on OpenFeature, switching later is a provider swap.

**OpenTelemetry Collector + Grafana LGTM — observability.** The app emits OTLP (traces, metrics, logs) to the Collector, which batches, scrubs attributes and forwards to backends. `grafana/otel-lgtm` bundles Grafana, Loki (logs), Tempo (traces), Prometheus (metrics) and its own collector in one container — the fastest way to a working RED dashboard locally. Grafana Labs states the image is for development, demo and testing, which matches this project. We still run a separate Collector so the pipeline (processors, PII attribute removal, fan-out) is visible and configured in the repo. *Rejected:* separate Grafana/Loki/Tempo/Prometheus containers (more moving parts for no learning gain at this size; revisit if we need retention or HA) and Jaeger + Prometheus (no log store, two UIs).

**GlitchTip — error tracking.** Accepts events from the official Sentry SDKs, so the code is the same as for Sentry. MIT licence; runs as a web container plus a worker, reusing PostgreSQL and Redis. *Rejected:* self-hosted Sentry. Its core is under the Functional Source License (FSL-1.1-Apache-2.0), which is source-available, not open source, and the self-hosted install needs roughly 16 GB RAM and dozens of containers (Kafka, ClickHouse, Snuba).

**Ollama — local LLM runtime.** Serves chat and embedding models over a local HTTP API (stage 8), so AI features run without an API key or sending candidate data off the machine. The `LlmPort` keeps the model provider replaceable; a hosted-provider adapter is optional. *Rejected:* vLLM (Apache-2.0, built for GPU serving throughput; heavy on a laptop) and LocalAI (MIT, broader scope than needed). Hosted APIs are allowed only as an optional adapter, never as a requirement for the showcase to run.

## Consequences

- One `docker compose up` brings the stack up on a developer machine. Resource use grows by stage; heavy services (OpenSearch, Ollama, GlitchTip) go behind compose profiles so the stage 2 core stays light.
- Every licence above is OSI-approved. Redis 8 (as chosen), Grafana, Loki, Tempo and k6 are under AGPLv3, which is copyleft for network use. We run them unmodified as separate services, which triggers no source-disclosure obligation for TalentFlow's own code. The licence policy check in stage 9 (DUTH-77) covers our dependencies, not these service images.
- Image tags are pinned (never `latest`) and every service has a healthcheck (DUTH-50).
- Credentials in compose and `.env.example` are local-only dev values, clearly marked; nothing in this stack is a production secret.
- The vendor-neutral production-hardening contract still holds: immutable images, migrations before rollout, readiness probes, OTel as the telemetry contract, no secrets in Git.
- `infra/opentofu/` and the `Infrastructure` CI workflow are out of scope and not maintained. They stay in the repository until a separate issue removes them.

## Revisit when

- Any chosen service changes licence away from an OSI-approved licence, or stops publishing an official image (as MinIO did).
- The project decides to deploy to a cloud again — then write a new ADR mapping each port to a managed service.

## References

- DUTH-43 decisions (2026-11-24) and [roadmap](../roadmap.md)
- Redis licensing: <https://redis.io/legal/licenses/>
- Elasticsearch AGPL option: <https://www.elastic.co/blog/elasticsearch-is-open-source-again>
- Garage S3 compatibility: <https://garagehq.deuxfleurs.fr/documentation/reference-manual/s3-compatibility/>
- MinIO community repository (archived; see its README for the maintenance notice): <https://github.com/minio/minio>
- Grafana `otel-lgtm` scope: <https://grafana.com/docs/opentelemetry/docker-lgtm/>
- Sentry licensing: <https://open.sentry.io/licensing>
