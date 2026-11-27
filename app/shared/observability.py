from __future__ import annotations

import json
import logging
import re
import time
from contextvars import ContextVar
from urllib.parse import urlsplit
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
from opentelemetry.trace import Span
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response

from app.shared.settings import Settings

correlation_id_context: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_CALENDAR_FEED_PATH_PATTERN = re.compile(r"/v1/calendar-feeds/[^/?]+\.ics")
_SEARCH_QUERY_PATTERN = re.compile(r"(^|[?&])((?:q|%71)=)[^&#]*")
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
broker_depth = Gauge("talentflow_broker_queue_depth", "RabbitMQ ready messages.", ("queue",))
consumer_outcomes = Counter(
    "talentflow_consumer_messages", "Consumer outcomes.", ("consumer", "outcome")
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
    insecure = _otlp_insecure(runtime_settings)
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=insecure))
    )
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint, insecure=insecure)
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint, insecure=insecure))
    )
    _logs.set_logger_provider(logger_provider)
    _telemetry_handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    _telemetry_configured = True


def _otlp_insecure(runtime_settings: Settings) -> bool:
    if runtime_settings.otel_exporter_otlp_insecure is not None:
        return runtime_settings.otel_exporter_otlp_insecure
    return urlsplit(runtime_settings.otel_exporter_otlp_endpoint).scheme != "https"


class SearchQueryRedactionFilter(logging.Filter):
    """Uvicorn stores the request target in argument 2 of its access record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) == 5:
            client, method, target, version, status = record.args
            if isinstance(target, str):
                record.args = (client, method, _redact_search_query(target), version, status)
        return True


def _redact_search_query(value: str) -> str:
    return _SEARCH_QUERY_PATTERN.sub(r"\g<1>\g<2>REDACTED", value)


def configure_logging() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, SearchQueryRedactionFilter) for item in access_logger.filters):
        access_logger.addFilter(SearchQueryRedactionFilter())
    root = logging.getLogger()
    if any(isinstance(handler.formatter, JsonFormatter) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler, *([_telemetry_handler] if _telemetry_handler else [])]
    root.setLevel(logging.INFO)


def record_worker_ready(worker_name: str, ready: bool) -> None:
    meter = metrics.get_meter("talentflow.workers")
    meter.create_up_down_counter("talentflow.worker.ready").add(
        1 if ready else -1, {"worker.name": worker_name}
    )


def record_worker_cycle(worker_name: str, backlog: int, duration_seconds: float) -> None:
    meter = metrics.get_meter("talentflow.workers")
    attributes = {"worker.name": worker_name}
    meter.create_counter("talentflow.worker.cycles").add(1, attributes)
    meter.create_histogram("talentflow.worker.backlog").record(backlog, attributes)
    meter.create_histogram("talentflow.worker.cycle.duration", unit="s").record(
        duration_seconds, attributes
    )


def record_worker_failure(worker_name: str) -> None:
    metrics.get_meter("talentflow.workers").create_counter("talentflow.worker.failures").add(
        1, {"worker.name": worker_name}
    )


def instrument_app(app: FastAPI) -> None:
    if not getattr(app.state, "otel_instrumented", False):
        FastAPIInstrumentor.instrument_app(app, server_request_hook=_redact_calendar_feed_span)
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


def _redact_calendar_feed_span(span: Span, scope: dict[str, object]) -> None:
    path = scope.get("path")
    if isinstance(path, str) and _CALENDAR_FEED_PATH_PATTERN.fullmatch(path):
        sanitized_path = "/v1/calendar-feeds/{token}.ics"
        for attribute in ("url.path", "http.target", "http.url", "url.full"):
            span.set_attribute(attribute, sanitized_path)

    # The hook runs after ASGI has populated the URL attributes, before export.
    attributes = getattr(span, "attributes", None) or {}
    for attribute in ("url.query", "http.target", "http.url", "url.full"):
        value = attributes.get(attribute)
        if isinstance(value, str):
            redacted = _redact_search_query(value)
            if redacted != value:
                span.set_attribute(attribute, redacted)


careers_applications = Counter(
    "careers_applications_total", "Anonymous application outcomes", ["outcome"]
)
