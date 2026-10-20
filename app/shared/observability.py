from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar
from uuid import uuid4

from fastapi import FastAPI, Request
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response

correlation_id_context: ContextVar[str | None] = ContextVar("correlation_id", default=None)

http_requests = Counter(
    "talentflow_http_requests",
    "HTTP requests completed by method, route, and status.",
    ("method", "route", "status"),
)
http_duration = Histogram(
    "talentflow_http_request_duration_seconds",
    "HTTP request duration in seconds by method and route.",
    ("method", "route"),
)
command_conflicts = Counter(
    "talentflow_command_conflicts",
    "Optimistic concurrency conflicts by aggregate type.",
    ("aggregate_type",),
)
outbox_backlog = Gauge("talentflow_outbox_backlog", "Pending outbox events.")
delivery_attempts = Counter(
    "talentflow_delivery_attempts",
    "Notification delivery attempts by outcome.",
    ("outcome",),
)
dead_letters = Gauge("talentflow_dead_letters", "Notification deliveries in dead-letter state.")
worker_claims = Counter(
    "talentflow_worker_claims",
    "Worker delivery claim outcomes.",
    ("outcome",),
)
rate_limit_rejections = Counter(
    "talentflow_rate_limit_rejections",
    "HTTP requests rejected by the rate limiter.",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        correlation_id = correlation_id_context.get()
        if correlation_id:
            payload["correlation_id"] = correlation_id
        for key in ("event", "delivery_id", "outcome", "published", "delivered"):
            if value := getattr(record, key, None):
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    if any(isinstance(handler.formatter, JsonFormatter) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    root.setLevel(logging.INFO)


def instrument_app(app: FastAPI) -> None:
    if not getattr(app.state, "otel_instrumented", False):
        FastAPIInstrumentor.instrument_app(app)
        app.state.otel_instrumented = True

    @app.middleware("http")
    async def observe_request(request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-Id") or str(uuid4())
        token = correlation_id_context.set(correlation_id)
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            correlation_id_context.reset(token)
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        http_requests.labels(request.method, route_path, str(response.status_code)).inc()
        http_duration.labels(request.method, route_path).observe(time.perf_counter() - started_at)
        response.headers["X-Correlation-Id"] = correlation_id
        return response


def prometheus_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
