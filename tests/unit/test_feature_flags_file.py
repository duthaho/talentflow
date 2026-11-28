import json
import time
from dataclasses import replace
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client import REGISTRY as METRICS

from app.modules.feature_flags.application.flags import (
    ONBOARDING_SAGA,
    REGISTRY,
    WEBHOOKS_DELIVERY,
    WEBHOOKS_OUTBOUND,
    Context,
    Flag,
)
from app.modules.feature_flags.infrastructure.openfeature import OpenFeatureFlags
from app.shared.observability import JsonFormatter
from app.shared.settings import Settings
from scripts.validate_feature_flags import validate


def test_role_scope_and_context_projection(tmp_path):
    document = json.loads(Path("tests/fixtures/flags-on.json").read_text())
    role = Flag("release.webhooks.roles", scope="request")
    document["flags"][role.key] = {
        "state": "ENABLED",
        "variants": {"on": True, "off": False},
        "defaultVariant": "off",
        "targeting": {"if": [{"===": [{"var": "role"}, "tenant_admin"]}, "on", None]},
    }
    # Tenant-scoped registry flags ignore an incoming role even if the rules mention it.
    document["flags"][WEBHOOKS_OUTBOUND.key]["defaultVariant"] = "off"
    document["flags"][WEBHOOKS_OUTBOUND.key]["targeting"] = document["flags"][role.key]["targeting"]
    path = tmp_path / "flags.json"
    path.write_text(json.dumps(document))
    adapter = OpenFeatureFlags(Settings(flagd_offline_flag_source_path=str(path)))
    try:
        assert adapter.is_enabled(role, Context("tenant", "tenant_admin"))
        assert not adapter.is_enabled(role, Context("tenant", "recruiter"))
        assert not adapter.is_enabled(WEBHOOKS_OUTBOUND, Context("tenant", "tenant_admin"))
        with pytest.raises(ValueError, match="Retired"):
            adapter.is_enabled(replace(role, retired=True), Context("tenant"))
    finally:
        adapter.close()


def test_rpc_fallback_deadline_and_scrubbed_telemetry(caplog):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    adapter = OpenFeatureFlags(
        Settings(feature_flags_provider="flagd", flagd_host="127.0.0.1", flagd_port=1)
    )
    try:
        with provider.get_tracer("test").start_as_current_span("flags"):
            for _ in range(3):
                started = time.monotonic()
                result = adapter.evaluate(
                    WEBHOOKS_OUTBOUND, Context("opaque-tenant", "tenant_admin")
                )
                assert not result.enabled and result.error
                assert time.monotonic() - started < 0.3
        events = exporter.get_finished_spans()[0].events
        assert len(events) == 3
        allowed = {
            "feature_flag.key",
            "feature_flag.result.variant",
            "feature_flag.result.reason",
            "feature_flag.provider.name",
            "error.type",
        }
        assert all(
            event.name == "feature_flag.evaluation" and set(event.attributes) == allowed
            for event in events
        )
        warnings = [r for r in caplog.records if r.message == "feature_flag_evaluation_failed"]
        assert len(warnings) == 1
        payload = json.loads(JsonFormatter().format(warnings[0]))
        assert payload["flag_key"] == WEBHOOKS_OUTBOUND.key and payload["error_code"]
        assert "opaque-tenant" not in str(events) + caplog.text + str(payload)
        samples = [
            sample
            for metric in METRICS.collect()
            if metric.name == "talentflow_feature_flag_evaluations"
            for sample in metric.samples
        ]
        assert samples and all(
            set(sample.labels) == {"flag_key", "variant", "reason"} for sample in samples
        )
    finally:
        adapter.close()
        provider.shutdown()


def test_file_schema_lifecycle_and_registry():
    validate(json.loads(Path("flags/talentflow.flagd.json").read_text()))


@pytest.mark.parametrize("failure", ["missing", "type", "disabled"])
def test_provider_errors_never_enable_the_capability(tmp_path, failure):
    document = json.loads(Path("tests/fixtures/flags-on.json").read_text())
    if failure == "missing":
        del document["flags"][WEBHOOKS_OUTBOUND.key]
    elif failure == "type":
        document["flags"][WEBHOOKS_OUTBOUND.key]["variants"]["on"] = "true"
    else:
        document["flags"][WEBHOOKS_OUTBOUND.key]["state"] = "DISABLED"
    path = tmp_path / "flags.json"
    path.write_text(json.dumps(document))
    adapter = OpenFeatureFlags(Settings(flagd_offline_flag_source_path=str(path)))
    try:
        assert not adapter.is_enabled(WEBHOOKS_OUTBOUND, Context("tenant"))
    finally:
        adapter.close()


@pytest.mark.parametrize(
    "mutation,rule",
    [
        ("schema", 1),
        ("name", 2),
        ("metadata", 3),
        ("expired", 4),
        ("too_long", 4),
        ("missing", 5),
        ("role", 6),
        ("fallback", 7),
        ("variants", 7),
        ("else", 8),
        ("ops_then", 8),
        ("release_then", 8),
        ("ops_fractional", 8),
        ("fractional_sum", 8),
        ("fractional_bucket", 8),
        ("retired_off", 9),
        ("retired_reference", 9),
    ],
)
def test_lifecycle_rejects_each_invalid_stage(tmp_path, mutation, rule):
    document = json.loads(Path("flags/talentflow.flagd.json").read_text())
    registry = REGISTRY
    release = document["flags"][WEBHOOKS_OUTBOUND.key]
    ops = document["flags"][WEBHOOKS_DELIVERY.key]
    sources = []
    if mutation == "schema":
        release["state"] = "UNKNOWN"
    if mutation == "name":
        document["flags"]["bad-name"] = document["flags"].pop(WEBHOOKS_OUTBOUND.key)
        registry = (replace(WEBHOOKS_OUTBOUND, key="bad-name"), WEBHOOKS_DELIVERY, ONBOARDING_SAGA)
    if mutation == "metadata":
        del release["metadata"]["owner"]
    if mutation == "expired":
        release["metadata"]["expiresAt"] = "2026-01-01"
    if mutation == "too_long":
        release["metadata"]["expiresAt"] = "2028-01-01"
    if mutation == "missing":
        del document["flags"][WEBHOOKS_OUTBOUND.key]
    if mutation == "role":
        release["targeting"]["if"][0] = {"var": "role"}
    if mutation == "fallback":
        registry = (replace(WEBHOOKS_OUTBOUND, fallback=True), WEBHOOKS_DELIVERY, ONBOARDING_SAGA)
    if mutation == "variants":
        release["variants"]["on"] = False
    if mutation == "else":
        ops["targeting"]["if"][2] = "on"
    if mutation == "ops_then":
        ops["targeting"]["if"][1] = "on"
    if mutation == "release_then":
        release["targeting"]["if"][1] = "off"
    if mutation == "ops_fractional":
        ops["targeting"]["if"][2] = {"fractional": [["on", 25], ["off", 75]]}
    if mutation == "fractional_sum":
        release["targeting"]["if"][2] = {"fractional": [["on", 25], ["off", 70]]}
    if mutation == "fractional_bucket":
        release["targeting"]["if"][2] = {"fractional": [["other", 25], ["off", 75]]}
    if mutation.startswith("retired"):
        registry = (replace(WEBHOOKS_OUTBOUND, retired=True), WEBHOOKS_DELIVERY, ONBOARDING_SAGA)
        if mutation == "retired_reference":
            release["defaultVariant"] = "on"
            del release["targeting"]
            source = tmp_path / "still_used.py"
            source.write_text(
                "from app.modules.feature_flags.application.flags import WEBHOOKS_OUTBOUND\n"
            )
            sources = [source]
    with pytest.raises(ValueError, match=f"rule {rule}"):
        validate(document, registry, sources=sources)


@pytest.mark.parametrize(
    "stage",
    [
        "new",
        "global_empty",
        "global_listed",
        "restore",
        "percentage",
        "rollout",
        "retired",
        "removed",
    ],
)
def test_all_valid_lifecycle_stages_pass(stage):
    document = json.loads(Path("flags/talentflow.flagd.json").read_text())
    registry = REGISTRY
    release = document["flags"][WEBHOOKS_OUTBOUND.key]
    ops = document["flags"][WEBHOOKS_DELIVERY.key]
    if stage.startswith("global"):
        ops["defaultVariant"] = "off"
    if stage in ("global_listed", "restore"):
        ops["targeting"]["if"][0]["in"][1] = ["00000000-0000-4000-8000-000000000001"]
    if stage == "percentage":
        release["targeting"]["if"][2] = {"fractional": [["on", 25], ["off", 75]]}
    if stage in ("rollout", "retired"):
        release["defaultVariant"] = "on"
        del release["targeting"]
    if stage == "retired":
        registry = (replace(WEBHOOKS_OUTBOUND, retired=True), WEBHOOKS_DELIVERY, ONBOARDING_SAGA)
    if stage == "removed":
        del document["flags"][WEBHOOKS_OUTBOUND.key]
        registry = (WEBHOOKS_DELIVERY, ONBOARDING_SAGA)
    validate(document, registry, sources=[])


def test_sdk_is_confined_to_adapter_and_keys_to_registry():
    registry = Path("app/modules/feature_flags/application/flags.py")
    adapter = Path("app/modules/feature_flags/infrastructure/openfeature.py")
    for path in Path("app").rglob("*.py"):
        if path != adapter:
            assert not any(
                line.startswith(("import openfeature", "from openfeature"))
                for line in path.read_text().splitlines()
            ), path
        if path != registry:
            assert all(f'"{flag.key}"' not in path.read_text() for flag in REGISTRY), path


def test_flagd_network_is_private_and_runtime_configuration_fails_closed():
    import yaml

    services = yaml.safe_load(Path("docker-compose.yml").read_text())["services"]
    service = services["flagd"]
    assert service["networks"] == ["default"]
    assert "ports" not in service
    assert service["user"] == "65532:65532"
    assert service["volumes"] == ["./flags:/etc/flagd:ro"]
    assert "--debug" not in service["command"]
    assert "--log-format" in service["command"]
    assert "@sha256:" in Path("Dockerfile.flagd").read_text()
    assert not any("FLAGD" in key for key in services["web"]["environment"])
    for name in ("api", "webhook-worker"):
        assert services[name]["environment"]["FEATURE_FLAGS_PROVIDER"] == "flagd"
        assert services[name]["environment"]["FLAGD_CACHE"] == "disabled"
        assert services[name]["environment"]["FLAGD_DEADLINE_MS"] == 200
        assert services[name]["depends_on"]["flagd"]["condition"] == "service_started"
