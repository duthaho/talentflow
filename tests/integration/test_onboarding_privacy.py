"""S5: remote error bodies must not escape the provisioning boundary."""

import logging

import httpx
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import select
from test_onboarding import process as process

from app.modules.onboarding.application.run_due import DueStepRunner
from app.modules.onboarding.infrastructure.adapters import HttpHris, KeycloakDirectory
from app.modules.onboarding.infrastructure.models import Step
from app.modules.onboarding.infrastructure.settings import OnboardingSettings


@pytest.mark.parametrize("step", ["create_employee", "provision_account"])
@pytest.mark.parametrize("fault", [409, 500, "timeout"])
def test_provisioning_faults_keep_pii_out_of_errors_logs_and_spans(process, caplog, step, fault):
    sessions, repository, runner, effects, now, _ = process
    if step == "provision_account":
        assert runner.run_one()  # Reach the directory boundary without a remote HRIS dependency.
    marker = "PrivateName private@example.test"
    calls = []

    def respond(request):
        calls.append(request)
        assert "PrivateName" not in str(request.url)
        assert "private@example.test" not in str(request.url)
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 300})
        if request.method == "GET":
            return httpx.Response(200, json=[])
        if fault == "timeout":
            raise httpx.ReadTimeout(marker)
        return httpx.Response(
            fault, json={"errorMessage": "User exists with same email: " + marker}
        )

    transport = httpx.MockTransport(respond)
    settings = OnboardingSettings()
    controlled = DueStepRunner(
        repository,
        HttpHris(settings, transport) if step == "create_employee" else effects,
        KeycloakDirectory(settings, transport) if step == "provision_account" else effects,
        clock=lambda: now[0],
    )
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        with caplog.at_level(logging.DEBUG):
            with provider.get_tracer(__name__).start_as_current_span("onboarding.attempt"):
                assert controlled.run_one()
        with sessions() as session:
            failed = session.scalar(select(Step).where(Step.step == step))
            expected = {
                409: "hris_rejected" if step == "create_employee" else "directory_conflict",
                500: "TransientStepError",
                "timeout": "AttemptTimeout",
            }[fault]
            assert failed.last_error == expected
        spans = exporter.get_finished_spans()
        assert spans and calls
        captured = caplog.text + failed.last_error + "".join(span.to_json() for span in spans)
        assert "PrivateName" not in captured
        assert "private@example.test" not in captured
    finally:
        provider.shutdown()
