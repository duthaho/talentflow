# Local observability

`docker compose up --wait` starts the OpenTelemetry Collector and Grafana LGTM with the API. The API and each long-running worker export OTLP traces, metrics and structured logs through the Collector only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. This keeps export disabled in unit tests and non-compose development by default.

Open [Grafana](http://localhost:3001) and select **Dashboards → TalentFlow → TalentFlow RED** to view route request rate, server-error rate and p95 duration. Set `GRAFANA_PORT` if 3001 is unavailable. To find one request trace, make a request to `http://localhost:8000/health/live`, then open **Explore → Tempo** and query `{ resource.service.name = "talentflow-api" }`.

The Collector is kept separate from the LGTM development bundle so the OTLP boundary, batching and future attribute-scrubbing policy are explicit, reviewable configuration. Its container healthcheck validates the configuration because the pinned Collector image is distroless; the running Collector also exposes the `health_check` extension on port 13133 inside the compose network. Grafana LGTM is intentionally local/demo-only, as recorded in ADR-003.
