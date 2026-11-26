import io
import logging
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider

from app.shared.observability import _redact_calendar_feed_span, configure_logging


@pytest.mark.parametrize(
    "target",
    [
        "/v1/candidate-cases?stage=screening&q=private%40example.test&limit=20&q=second",
        "/v1/candidate-cases?%71=private%40example.test&stage=screening",
    ],
)
def test_configured_uvicorn_access_logger_redacts_formatted_arguments(target):
    configure_logging()
    configure_logging()  # Reconfiguration must not install duplicate filters.
    logger = logging.getLogger("uvicorn.access")
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    old_handlers, old_level, old_propagate = logger.handlers, logger.level, logger.propagate
    try:
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:123", "GET", target, "1.1", 200)
    finally:
        logger.handlers, logger.level, logger.propagate = old_handlers, old_level, old_propagate
    message = output.getvalue()
    assert "private" not in message
    assert "second" not in message
    assert "stage=screening" in message
    assert "REDACTED" in message


def test_uvicorn_access_logger_leaves_non_search_requests_unchanged():
    configure_logging()
    logger = logging.getLogger("uvicorn.access")
    record = logger.makeRecord(
        logger.name,
        logging.INFO,
        "",
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", "/v1/candidate-cases?stage=screening", "1.1", 200),
        None,
    )
    before = record.getMessage()
    assert logger.filter(record)
    assert record.getMessage() == before


@pytest.mark.parametrize(
    "query",
    ["q=private%40example.test", "%71=private%40example.test", "q=first&q=private%40example.test"],
)
def test_search_span_redacts_all_url_attributes(query):
    provider = TracerProvider()
    with provider.get_tracer(__name__).start_span("request") as span:
        attributes = {
            "url.query": f"stage=screening&{query}&limit=20",
            "http.target": f"/v1/candidate-cases?stage=screening&{query}",
            "http.url": f"http://testserver/v1/candidate-cases?stage=screening&{query}",
            "url.full": f"http://testserver/v1/candidate-cases?stage=screening&{query}",
        }
        span.set_attributes(attributes)
        _redact_calendar_feed_span(span, {"path": "/v1/candidate-cases"})
        for key in attributes:
            assert "private" not in span.attributes[key]
            assert "first" not in span.attributes[key]
            assert "stage=screening" in span.attributes[key]
            assert "REDACTED" in span.attributes[key]
    provider.shutdown()


def test_span_without_search_is_unchanged():
    provider = TracerProvider()
    with provider.get_tracer(__name__).start_span("request") as span:
        attributes = {
            "http.url": "http://testserver/v1/candidate-cases?stage=screening",
            "url.query": "stage=screening",
        }
        span.set_attributes(attributes)
        _redact_calendar_feed_span(span, {"path": "/v1/candidate-cases"})
        assert dict(span.attributes) == attributes
    provider.shutdown()


def test_collector_redacts_search_in_each_url_attribute():
    config = Path("observability/otel-collector.yaml").read_text()
    for attribute in ("url.query", "http.target", "http.url", "url.full"):
        assert (
            f'replace_pattern(attributes["{attribute}"], "(^|[?&])((q|%71)=)[^&#]*", "$${{1}}$${{2}}REDACTED")'
            in config
        )
    assert "processors: [transform/redact_calendar_feed_tokens, batch]" in config


@pytest.mark.parametrize("semconv", ["", "http"])
def test_instrumented_request_does_not_export_search_term(semconv):
    import os
    import subprocess
    import sys

    script = """
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from fastapi.testclient import TestClient

exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)
from app.main import create_app
with TestClient(create_app('sqlite://')) as client:
    client.get('/v1/candidate-cases', params={'q': 'private-search-123', 'stage': 'screening'})
provider.force_flush()
spans = exporter.get_finished_spans()
assert spans
for span in spans:
    assert 'private-search-123' not in str(span.attributes)
assert any('REDACTED' in str(span.attributes) for span in spans)
provider.shutdown()
"""
    subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "OTEL_SEMCONV_STABILITY_OPT_IN": semconv},
        check=True,
    )
