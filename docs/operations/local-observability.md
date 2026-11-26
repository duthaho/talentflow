# Local observability

`docker compose up --wait` starts the OpenTelemetry Collector and Grafana LGTM with the API. The API and each long-running worker export OTLP traces, metrics and structured logs through the Collector only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. This keeps export disabled in unit tests and non-compose development by default.

Open [Grafana](http://localhost:3001) and select **Dashboards → TalentFlow → TalentFlow RED** to view route request rate, server-error rate and p95 duration. Set `GRAFANA_PORT` if 3001 is unavailable. To find one request trace, make a request to `http://localhost:8000/health/live`, then open **Explore → Tempo** and query `{ resource.service.name = "talentflow-api" }`.

Grafana LGTM is anonymous Admin by default and is bound to `127.0.0.1` only. It is suitable for local development and must never be published beyond the local machine.

The Collector is kept separate from the LGTM development bundle so the OTLP boundary, batching and future attribute-scrubbing policy are explicit, reviewable configuration. Its container healthcheck validates the configuration because the pinned Collector image is distroless; the running Collector also exposes the `health_check` extension on port 13133 inside the compose network. Grafana LGTM is intentionally local/demo-only, as recorded in ADR-003.

Candidate search (`GET /v1/candidate-cases?q=...`) can contain names or emails. The API redacts every `q` value in the uvicorn access log and the OTel URL attributes (`url.query`, `http.target`, `http.url`, `url.full`); the Collector repeats the URL redaction before exporting traces. SQLAlchemy hides bound parameters in database errors. Calendar feed token redaction remains in the same span hook and Collector processor. Future proxies and error-reporting integrations must preserve these protections. See [the DUTH-122 contract](../specs/DUTH-122.md).
