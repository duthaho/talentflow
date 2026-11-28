"""Opt-in real RPC reload/outage and PostgreSQL replica/migration checks.

Run: DUTH65_LIVE_FLAGS=1 uv run --python 3.13 python -m pytest
     tests/integration/test_feature_flags_live.py --no-cov
Only this fixture's unique Compose project is created and removed.
"""

import json
import os
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from test_webhooks import Sender, create, enqueue, worker

from app.main import create_app
from app.modules.feature_flags.application.flags import (
    WEBHOOKS_DELIVERY,
    WEBHOOKS_OUTBOUND,
    Context,
)
from app.modules.webhooks.infrastructure.egress import EgressGuard
from app.modules.webhooks.infrastructure.management import aware
from app.modules.webhooks.infrastructure.models import Delivery, DeliveryPause, Endpoint
from app.shared.database import build_engine
from app.shared.settings import Settings

pytestmark = pytest.mark.skipif(
    os.getenv("DUTH65_LIVE_FLAGS") != "1", reason="opt-in disposable flagd/PostgreSQL Compose test"
)


def eventually(assertion, seconds=5):
    deadline = time.monotonic() + seconds
    while True:
        try:
            assertion()
            return
        except AssertionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    root = tmp_path_factory.mktemp("flagd-live")
    root.chmod(0o755)
    # Docker binds the directory, so an atomic editor save is visible to flagd.
    definitions = root / "flags"
    definitions.mkdir(mode=0o755)
    path = definitions / "talentflow.flagd.json"
    path.write_text(Path("flags/talentflow.flagd.json").read_text())
    services = yaml.safe_load(Path("docker-compose.yml").read_text())["services"]
    flagd = services["flagd"]
    flagd["build"]["context"] = str(Path.cwd())
    flagd["volumes"] = [f"{definitions}:/etc/flagd:ro"]
    # Docker may reallocate an anonymous published port when restarting a container.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        fixed_port = reservation.getsockname()[1]
    flagd["ports"] = [f"127.0.0.1:{fixed_port}:8013"]
    postgres = services["postgres"]
    postgres["ports"] = ["127.0.0.1::5432"]
    postgres["volumes"] = []
    compose_file = root / "compose.yaml"
    compose_file.write_text(yaml.safe_dump({"services": {"flagd": flagd, "postgres": postgres}}))
    project = f"duth65-{uuid4().hex[:8]}"

    def compose(*arguments):
        return subprocess.check_output(
            ["docker", "compose", "-p", project, "-f", str(compose_file), *arguments], text=True
        )

    try:
        compose("up", "-d", "--build", "--wait", "--wait-timeout", "45")
        flag_port = int(compose("port", "flagd", "8013").strip().rsplit(":", 1)[1])
        pg_port = int(compose("port", "postgres", "5432").strip().rsplit(":", 1)[1])
        yield (
            path,
            flag_port,
            f"postgresql+psycopg://talentflow:talentflow@127.0.0.1:{pg_port}/talentflow",
            compose,
        )
    finally:
        compose("down", "-v", "--remove-orphans", "--rmi", "local")


def test_real_rpc_atomic_file_reload_global_stop_and_outage_recovery(stack):
    path, port, _, compose = stack
    settings = Settings(
        feature_flags_provider="flagd",
        flagd_host="127.0.0.1",
        flagd_port=port,
        rate_limit_enabled=False,
    )
    app = create_app("sqlite://", settings)
    document = json.loads(path.read_text())
    # Two unlisted tenants: defaultVariant must really govern a global stop.
    document["flags"][WEBHOOKS_OUTBOUND.key].pop("targeting")
    document["flags"][WEBHOOKS_OUTBOUND.key]["defaultVariant"] = "on"

    def save():
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(document))
        temporary.replace(path)

    save()
    with TestClient(app) as client:

        async def resolver(host, port):
            return ["93.184.216.34"]

        app.state.webhook_egress_guard = EgressGuard(resolver=resolver)
        tenant = client.post(
            "/v1/tenants", json={"name": "Live", "slug": "live", "admin_id": "live-admin"}
        ).json()["id"]
        api = app, client, {"X-Tenant-Id": tenant, "X-Actor-Id": "live-admin"}

        def enabled():
            assert client.get("/v1/me", headers=api[2]).json()["features"]["webhooks"] == {
                "enabled": True,
                "delivery_paused": False,
            }

        eventually(enabled)
        assert create(api).status_code == 201
        _, ident = enqueue(api)
        sender = Sender()
        runner = worker(api, sender=sender)
        document["flags"][WEBHOOKS_DELIVERY.key]["defaultVariant"] = "off"
        save()

        def globally_paused():
            state = client.get("/v1/me", headers=api[2]).json()["features"]["webhooks"]
            assert state == {"enabled": True, "delivery_paused": True}
            assert not app.state.feature_flags.is_enabled(
                WEBHOOKS_DELIVERY, Context("another-unlisted-tenant")
            )

        eventually(globally_paused)
        assert runner.deliver_pending() == 0 and not sender.calls
        compose("stop", "flagd")

        def unavailable():
            started = time.monotonic()
            result = app.state.feature_flags.evaluate(WEBHOOKS_OUTBOUND, Context(tenant))
            assert result.error and not result.enabled
            assert time.monotonic() - started < 0.3

        eventually(unavailable)
        assert create(api, url="https://new.example").status_code == 403
        assert client.get("/v1/webhook-endpoints", headers=api[2]).status_code == 200
        assert client.get("/health/ready").status_code == 200
        runner.snapshot_at = None
        assert runner.deliver_pending() == 0
        with app.state.session_factory() as session:
            assert session.get(Delivery, ident).attempt_count == 0
            assert session.get(DeliveryPause, tenant).reason == "flag_error"
        document["flags"][WEBHOOKS_DELIVERY.key]["defaultVariant"] = "on"
        save()
        compose("start", "flagd")
        eventually(enabled, seconds=15)
        runner.snapshot_at = None
        assert runner.deliver_pending() == 1
        with app.state.session_factory() as session:
            assert session.get(Delivery, ident).attempt_count == 1
            assert session.get(DeliveryPause, tenant) is None
        document["flags"][WEBHOOKS_OUTBOUND.key]["defaultVariant"] = "off"
        save()
        eventually(lambda: assert_disabled(client, api[2]))


def assert_disabled(client, headers):
    assert client.get("/v1/me", headers=headers).json()["features"]["webhooks"] == {
        "enabled": False,
        "delivery_paused": True,
    }


def test_postgres_migration_roundtrip_and_two_workers_resume_once(stack, monkeypatch, tmp_path):
    _, _, url, _ = stack
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config()
    config.set_main_option("script_location", "migrations")
    command.upgrade(config, "head")
    engine = build_engine(url)
    assert inspect(engine).has_table("webhook_delivery_pauses")
    command.downgrade(config, "d127a001")
    assert not inspect(engine).has_table("webhook_delivery_pauses")
    command.upgrade(config, "head")
    engine.dispose()
    app = create_app(url, Settings(rate_limit_enabled=False))
    with TestClient(app) as client:
        tenant = client.post(
            "/v1/tenants", json={"name": "Race", "slug": "race", "admin_id": "race-admin"}
        ).json()["id"]
        api = app, client, {"X-Tenant-Id": tenant, "X-Actor-Id": "race-admin"}

        async def resolver(host, port):
            return ["93.184.216.34"]

        app.state.webhook_egress_guard = EgressGuard(resolver=resolver)
        endpoint = create(api).json()
        _, ident = enqueue(api)
        now = datetime.now(UTC)
        streak = now - timedelta(hours=70)
        with app.state.session_factory.begin() as session:
            session.get(Endpoint, endpoint["id"]).failure_streak_started_at = streak
            session.add(
                DeliveryPause(
                    tenant_id=tenant, paused_since=now - timedelta(days=3), reason="flag_off"
                )
            )
        first = worker(api, clock=lambda: now)
        second = worker(api, clock=lambda: now)
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda runner: runner.refresh_snapshot(), (first, second)))
        with app.state.session_factory() as session:
            assert aware(
                session.get(Endpoint, endpoint["id"]).failure_streak_started_at
            ) == streak + timedelta(days=3)
            assert session.get(DeliveryPause, tenant) is None
            assert session.get(Delivery, ident).attempt_count == 0
