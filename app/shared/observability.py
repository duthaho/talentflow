from __future__ import annotations

import json
import logging
import re
import time
from contextvars import ContextVar
from uuid import uuid4

from fastapi import FastAPI, Request
from opentelemetry import _logs, metrics, trace
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response

from app.shared.settings import Settings

correlation_id_context: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_telemetry_handler: LoggingHandler | None = None
_telemetry_configured = False

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
worker_last_success = Gauge(
    "talentflow_worker_last_success_unixtime",
    "Unix time of the last successful worker cycle.",
    ("worker",),
)
worker_backlog = Gauge("talentflow_worker_backlog", "Items left after a worker cycle.", ("worker",))
worker_ready = Gauge(
    "talentflow_worker_ready", "Whether a worker is ready to process work.", ("worker",)
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
        for key in ("event", "delivery_id", "outcome", "published", "delivered", "purged"):
            if value := getattr(record, key, None):
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_telemetry(runtime_settings: Settings) -> None:
    """Export telemetry only when an OTLP endpoint has been explicitly configured."""
    global _telemetry_configured, _telemetry_handler
    if _telemetry_configured or not runtime_settings.otel_exporter_otlp_endpoint:
        return

    resource = Resource.create({"service.name": runtime_settings.otel_service_name})
    endpoint = runtime_settings.otel_exporter_otlp_endpoint
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint, insecure=True)
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint, insecure=True))
    )
    _logs.set_logger_provider(logger_provider)
    _telemetry_handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    _telemetry_configured = True


def configure_logging() -> None:
    root = logging.getLogger()
    if any(isinstance(handler.formatter, JsonFormatter) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler, *([_telemetry_handler] if _telemetry_handler else [])]
    root.setLevel(logging.INFO)


def instrument_app(app: FastAPI) -> None:
    if not getattr(app.state, "otel_instrumented", False):
        FastAPIInstrumentor.instrument_app(app)
        app.state.otel_instrumented = True

    @app.middleware("http")
    async def observe_request(request: Request, call_next):
        requested_correlation_id = request.headers.get("X-Correlation-Id")
        correlation_id = (
            requested_correlation_id
            if requested_correlation_id
            and _CORRELATION_ID_PATTERN.fullmatch(requested_correlation_id)
            else str(uuid4())
        )
        request.state.correlation_id = correlation_id
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
