import json
import subprocess
import sys
from pathlib import Path


def test_configure_telemetry_installs_providers_and_logging_handler() -> None:
    script = """
import logging
from opentelemetry import _logs, metrics, trace
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider
from app.shared import observability
from app.shared.settings import Settings

settings = Settings(
    otel_exporter_otlp_endpoint='collector.example.test:4317',
    otel_service_name='talentflow-notification-worker',
)
observability.configure_telemetry(settings)
tracer_provider = trace.get_tracer_provider()
meter_provider = metrics.get_meter_provider()
logger_provider = _logs.get_logger_provider()
assert isinstance(tracer_provider, TracerProvider)
assert isinstance(meter_provider, MeterProvider)
assert isinstance(logger_provider, LoggerProvider)
assert tracer_provider.resource.attributes['service.name'] == 'talentflow-notification-worker'
assert meter_provider._sdk_config.resource.attributes['service.name'] == 'talentflow-notification-worker'
assert logger_provider._resource.attributes['service.name'] == 'talentflow-notification-worker'
observability.configure_logging()
assert any(isinstance(handler, LoggingHandler) for handler in logging.getLogger().handlers)
observability.configure_telemetry(Settings(
    otel_exporter_otlp_endpoint='other-collector.example.test:4317',
    otel_service_name='ignored',
))
assert trace.get_tracer_provider() is tracer_provider
assert metrics.get_meter_provider() is meter_provider
assert _logs.get_logger_provider() is logger_provider
"""
    subprocess.run([sys.executable, "-c", script], check=True)


def test_red_dashboard_uses_stable_http_semconv_metrics() -> None:
    dashboard_path = (
        Path(__file__).parents[2] / "observability/grafana/dashboards/talentflow-red.json"
    )
    dashboard = json.loads(dashboard_path.read_text())
    expressions = [panel["targets"][0]["expr"] for panel in dashboard["panels"]]

    assert all("http_server_request_duration_seconds" in expression for expression in expressions)
    assert all('service_name="talentflow-api"' in expression for expression in expressions)
    assert all('\\\\"' not in expression for expression in expressions)
    assert 'http_response_status_code=~"5.."' in expressions[1]
    assert all("http_route" in expression for expression in expressions)


def test_calendar_feed_token_is_redacted_before_span_export() -> None:
    script = """
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

token = 'QA-CALENDAR-FEED-TOKEN-123'
exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)

from app.main import create_app

with TestClient(create_app('sqlite://')) as client:
    response = client.get(f'/v1/calendar-feeds/{token}.ics')

provider.force_flush()
assert response.status_code == 404
assert exporter.get_finished_spans()
for span in exporter.get_finished_spans():
    assert token not in str(span.attributes)
"""
    subprocess.run([sys.executable, "-c", script], check=True)
