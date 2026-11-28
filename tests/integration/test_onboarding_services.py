"""Explicit real-service acceptance suite; CI must provide every named endpoint."""

import asyncio
import json
import multiprocessing
import os
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from test_onboarding import advance
from test_onboarding import process as process

from app.modules.notifications.application.email_delivery import EmailDeliverySender
from app.modules.notifications.infrastructure.smtp_email import SmtpEmailAdapter
from app.modules.notifications.persistence import NotificationDelivery
from app.modules.onboarding.application.run_due import DueStepRunner
from app.modules.onboarding.infrastructure.adapters import HttpHris, KeycloakDirectory
from app.modules.onboarding.infrastructure.consumer import OnboardingConsumer, decode_event
from app.modules.onboarding.infrastructure.models import Saga, Step
from app.modules.onboarding.infrastructure.settings import OnboardingSettings
from app.shared.rabbitmq import RabbitBroker


@pytest.fixture
def services():
    names = (
        "ONBOARDING_TEST_KEYCLOAK_URL",
        "ONBOARDING_TEST_HRIS_URL",
        "ONBOARDING_TEST_RABBITMQ_URL",
        "ONBOARDING_TEST_MAILPIT_URL",
        "ONBOARDING_TEST_SMTP_HOST",
    )
    if not all(os.getenv(n) for n in names):
        pytest.skip("real onboarding service endpoints required")
    settings = OnboardingSettings(
        keycloak_admin_url=os.environ[names[0]], hris_stub_url=os.environ[names[1]]
    )
    hris, directory = HttpHris(settings), KeycloakDirectory(settings)
    return settings, hris, directory


def real_runner(process, services):
    runner = DueStepRunner(process[1], services[1], services[2], clock=lambda: process[4][0])
    result = list(process)
    result[2] = runner
    return result


def cleanup(process, services):
    with process[0]() as s:
        saga = s.scalar(select(Saga))
    asyncio.run(services[2].delete_user(saga.candidate_case_id, saga.id))
    asyncio.run(services[1].delete_employee(saga.id))


def test_real_provisioning_and_mail(process, services):
    try:
        assert advance(real_runner(process, services)) == "completed"
        with process[0]() as s:
            saga = s.scalar(select(Saga))
            delivery = s.scalar(select(NotificationDelivery))
            hris = httpx.get(
                services[0].hris_stub_url + "/v1/employees/" + saga.id,
                headers={
                    "Authorization": "Bearer " + services[0].hris_stub_token.get_secret_value()
                },
            )
            assert hris.status_code == 200
            steps = list(
                s.scalars(select(Step).where(Step.saga_id == saga.id).order_by(Step.position))
            )
            assert hris.json()["employee_id"] == steps[0].external_ref

        async def check_user():
            async with httpx.AsyncClient() as client:
                token = await services[2].access_token(client)
                response = await client.get(
                    services[2].admin + "/users/" + steps[1].external_ref,
                    headers={"Authorization": "Bearer " + token},
                )
                assert response.status_code == 200, response.text
                user = response.json()
                assert not user["enabled"] and not user.get("credentials")
                assert user["attributes"]["onboarding_saga_id"] == [saga.id]

        asyncio.run(check_user())
        smtp = SmtpEmailAdapter(
            host=os.environ["ONBOARDING_TEST_SMTP_HOST"],
            port=int(os.getenv("ONBOARDING_TEST_SMTP_PORT", "1025")),
            sender="notifications@talentflow.local",
        )
        EmailDeliverySender(process[0], smtp)(delivery)
        mail = httpx.get(os.environ["ONBOARDING_TEST_MAILPIT_URL"] + "/api/v1/messages").json()
        assert mail["total"] >= 1
        latest = httpx.get(
            os.environ["ONBOARDING_TEST_MAILPIT_URL"]
            + "/api/v1/message/"
            + mail["messages"][0]["ID"]
        ).json()
        assert "PrivateName" in latest["Text"] and "onboarding ready" in latest["Subject"]
    finally:
        cleanup(process, services)


def test_keycloak_privilege_boundary(services):
    settings, hris, directory = services

    async def verify():
        async with httpx.AsyncClient() as client:
            token = await directory.access_token(client)
            headers = {"Authorization": "Bearer " + token}
            for realm in ("talentflow", "master"):
                response = await client.get(
                    settings.keycloak_admin_url + "/admin/realms/" + realm + "/users",
                    headers=headers,
                )
                assert response.status_code == 403, (realm, response.status_code)
            for realm in ("employees", "talentflow", "master"):
                response = await client.get(
                    settings.keycloak_admin_url + "/admin/realms/" + realm + "/clients",
                    headers=headers,
                )
                assert response.status_code == 403, (realm, response.status_code)
            # Bootstrap admin resolves role identifiers only for the negative test.
            admin = await client.post(
                settings.keycloak_admin_url + "/realms/master/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": "admin-cli",
                    "username": os.getenv("ONBOARDING_TEST_ADMIN_USER", "admin"),
                    "password": os.getenv(
                        "ONBOARDING_TEST_ADMIN_PASSWORD", "dev-keycloak-admin-password"
                    ),
                },
            )
            assert admin.status_code == 200
            privileged = {"Authorization": "Bearer " + admin.json()["access_token"]}
            clients = (await client.get(directory.admin + "/clients", headers=privileged)).json()
            management = next(c["id"] for c in clients if c["clientId"] == "realm-management")
            role = (
                await client.get(
                    directory.admin + "/clients/" + management + "/roles/realm-admin",
                    headers=privileged,
                )
            ).json()
            account = (
                await client.get(
                    directory.admin
                    + "/clients/"
                    + next(c["id"] for c in clients if c["clientId"] == "talentflow-onboarding")
                    + "/service-account-user",
                    headers=privileged,
                )
            ).json()
            response = await client.post(
                directory.admin
                + "/users/"
                + account["id"]
                + "/role-mappings/clients/"
                + management,
                headers=headers,
                json=[role],
            )
            assert response.status_code == 403, response.text

    asyncio.run(verify())


@pytest.mark.parametrize("step", ["create_employee", "provision_account", "schedule_tasks"])
def test_real_compensation(process, services, step):
    from app.modules.onboarding.infrastructure.faults import (
        FaultInjectingDirectory,
        FaultInjectingHris,
    )

    runner = DueStepRunner(
        process[1],
        FaultInjectingHris(services[1], {step}),
        FaultInjectingDirectory(services[2], {step}),
        clock=lambda: process[4][0],
    )
    process[1].faults = {step}
    controlled = list(process)
    controlled[2] = runner
    try:
        assert advance(controlled) == "compensated"
        with process[0]() as s:
            saga = s.scalar(select(Saga))
        response = httpx.get(
            services[0].hris_stub_url + "/v1/employees/" + saga.id,
            headers={"Authorization": "Bearer " + services[0].hris_stub_token.get_secret_value()},
        )
        assert response.status_code == 404

        async def absent():
            async with httpx.AsyncClient() as client:
                assert await services[2].owned(client, saga.candidate_case_id, saga.id) is None

        asyncio.run(absent())
    finally:
        cleanup(process, services)


def killed_attempt(sessions, configuration, now, step, connection):
    # A fresh pool in the child, never reuse a connection inherited across fork.
    sessions.kw["bind"].dispose(close=False)
    hris, directory = HttpHris(configuration), KeycloakDirectory(configuration)

    class CrashHris:
        async def upsert_employee(self, key, person):
            result = await hris.upsert_employee(key, person)
            connection.send(True)
            import signal

            signal.pause()
            return result

        async def delete_employee(self, key):
            await hris.delete_employee(key)

    class CrashDirectory:
        async def provision_user(self, case, saga, person):
            result = await directory.provision_user(case, saga, person)
            connection.send(True)
            import signal

            signal.pause()
            return result

        async def delete_user(self, case, saga):
            await directory.delete_user(case, saga)

    from app.modules.onboarding.infrastructure.repository import SqlAlchemySagaRepository

    DueStepRunner(
        SqlAlchemySagaRepository(sessions),
        CrashHris() if step == "create_employee" else hris,
        CrashDirectory() if step == "provision_account" else directory,
        clock=lambda: now,
    ).run_one()


@pytest.mark.parametrize("step", ["create_employee", "provision_account"])
def test_real_sigkill_recovery(process, services, step):
    actual = real_runner(process, services)
    child = None
    try:
        if step == "provision_account":
            assert actual[2].run_one()
        context = multiprocessing.get_context("fork")
        parent, pipe = context.Pipe()
        child = context.Process(
            target=killed_attempt, args=(process[0], services[0], process[4][0], step, pipe)
        )
        child.start()
        assert parent.poll(20), "remote effect not confirmed"
        assert parent.recv()
        assert child.pid != int(os.getenv("MULTICA_DAEMON_PID", "-1"))
        child.kill()
        child.join(10)
        assert child.exitcode == -9
        process[4][0] += timedelta(seconds=35)
        assert advance(actual) == "completed"
        with process[0]() as s:
            saga = s.scalar(select(Saga))
            steps = list(s.scalars(select(Step).where(Step.saga_id == saga.id)))
            assert next(x for x in steps if x.step == step).attempts == 2

        # Exactly one matching account and one stable employee key after replay.
        async def one_account():
            async with httpx.AsyncClient() as client:
                r = await services[2].call(
                    client,
                    "GET",
                    "/users",
                    params={"username": "tf-" + saga.candidate_case_id, "exact": "true"},
                )
                assert len(r.json()) == 1

        asyncio.run(one_account())
    finally:
        if child is not None and child.is_alive():
            assert child.pid != int(os.getenv("MULTICA_DAEMON_PID", "-1"))
            child.kill()
            child.join(10)
        cleanup(process, services)


def test_real_broker_inbox_dedup_and_poison(process, services):
    # Dedicated vhost, including its quorum queues, disappears after the test.
    url = os.environ["ONBOARDING_TEST_RABBITMQ_URL"]
    broker = RabbitBroker(
        url,
        consumer="onboarding",
        bindings=("candidate_case.stage_changed.v1", "candidate_case.erased.v1"),
    )

    class Flags:
        def is_enabled(self, *args):
            return True

    consumer = OnboardingConsumer(
        process[0], broker, process[1], Flags(), clock=lambda: process[4][0]
    )
    event = {
        **process[5],
        "specversion": "1.0",
        "source": "urn:talentflow:candidates",
        "datacontenttype": "application/json",
        "correlationid": str(uuid4()),
        "causationid": str(uuid4()),
    }
    event["data"] = {**event["data"], "candidate_case_id": event["subject"]}
    broker.connect()
    try:
        assert decode_event(json.dumps(event).encode()) == event
        broker.publish_event(event)
        broker.publish_event(event)
        consumer.drain()
        with process[0]() as s:
            from app.modules.notifications.persistence import InboxMessage

            assert (
                len(
                    list(
                        s.scalars(select(InboxMessage).where(InboxMessage.consumer == "onboarding"))
                    )
                )
                == 1
            )
        import pika

        broker.publish(
            "talentflow.events",
            "candidate_case.stage_changed.v1",
            b"not-json",
            pika.BasicProperties(),
        )
        consumer.drain()
        assert broker.depths()["onboarding.dlq"] == 1
    finally:
        broker.close()


def test_real_broker_recovers_flag_skipped_hire_without_duplicate(process, services):
    import pika
    from sqlalchemy import delete

    from app.modules.notifications.persistence import InboxMessage

    sessions, repo, _, _, now, original = process
    with sessions.begin() as session:
        session.execute(delete(Step))
        session.execute(delete(Saga))

    class Flags:
        enabled = False

        def is_enabled(self, *args):
            return self.enabled

    flags = Flags()
    broker = RabbitBroker(
        os.environ["ONBOARDING_TEST_RABBITMQ_URL"],
        consumer="onboarding",
        bindings=("candidate_case.stage_changed.v1", "candidate_case.erased.v1"),
    )
    consumer = OnboardingConsumer(sessions, broker, repo, flags, clock=lambda: now[0])
    event = {
        **original,
        "specversion": "1.0",
        "source": "urn:talentflow:candidates",
        "datacontenttype": "application/json",
        "correlationid": str(uuid4()),
        "causationid": str(uuid4()),
        "data": {**original["data"], "candidate_case_id": original["subject"]},
    }

    def republish():
        broker.publish("", "onboarding.events", json.dumps(event).encode(), pika.BasicProperties())
        consumer.drain()

    try:
        broker.connect()
        republish()
        with sessions() as session:
            assert session.get(InboxMessage, ("onboarding", event["id"])) is not None
            assert session.scalar(select(Saga)) is None
        flags.enabled = True
        republish()  # Enabling alone cannot bypass inbox deduplication.
        with sessions.begin() as session:
            assert session.scalar(select(Saga)) is None
            session.execute(
                delete(InboxMessage).where(
                    InboxMessage.consumer == "onboarding", InboxMessage.event_id == event["id"]
                )
            )
        republish()  # Execute the runbook's exact-entry removal/direct-queue recovery.
        with sessions() as session:
            saga_id = session.scalar(select(Saga.id))
            assert saga_id is not None
        with sessions.begin() as session:
            session.execute(
                delete(InboxMessage).where(
                    InboxMessage.consumer == "onboarding", InboxMessage.event_id == event["id"]
                )
            )
        republish()  # Repeating recovery also preserves the original saga identity.
        republish()
        with sessions() as session:
            assert list(session.scalars(select(Saga.id))) == [saga_id]
    finally:
        broker.close()


@pytest.mark.parametrize("explicit_date", [False, True])
def test_api_hire_outbox_to_real_broker_starts_and_completes(process, services, explicit_date):
    import time

    from fastapi.testclient import TestClient
    from sqlalchemy import delete

    from app.main import create_app
    from app.modules.candidates.persistence import CandidateCase
    from app.modules.notifications.application.outbox_publisher import OutboxPublisher
    from app.modules.offers.persistence import Offer
    from app.shared.settings import Settings

    sessions, repo, runner, effects, now, event = process
    with sessions.begin() as s:
        s.execute(delete(Step))
        s.execute(delete(Saga))
        s.get(CandidateCase, event["subject"]).stage = "offer_approved"
        s.add(
            Offer(
                tenant_id=event["tenantid"],
                candidate_case_id=event["subject"],
                title="Engineer",
                annual_salary=80000,
                currency="USD",
                status="approved",
                created_by="hire",
            )
        )
    app = create_app("sqlite://", Settings(rate_limit_enabled=False))
    broker = RabbitBroker(
        os.environ["ONBOARDING_TEST_RABBITMQ_URL"],
        consumer="onboarding",
        bindings=("candidate_case.stage_changed.v1", "candidate_case.erased.v1"),
    )
    broker.connect()
    try:
        with TestClient(app) as client:
            app.state.session_factory = sessions
            headers = {"X-Tenant-Id": event["tenantid"], "X-Actor-Id": "hire", "If-Match": '"1"'}
            started = time.monotonic()
            from datetime import UTC, datetime

            start_date = (datetime.now(UTC).date() + timedelta(days=365)).isoformat()
            response = client.patch(
                "/v1/candidate-cases/" + event["subject"] + "/stage",
                headers=headers,
                json={
                    "target_stage": "hired",
                    **({"start_date": start_date} if explicit_date else {}),
                },
            )
            assert response.status_code == 200, response.text
            if explicit_date:
                assert response.json()["hire_start_date"] == start_date
            assert OutboxPublisher(sessions, broker).publish_pending() == 1
            consumer = OnboardingConsumer(
                sessions, broker, repo, app.state.feature_flags, clock=lambda: now[0]
            )
            consumer.drain()
            assert advance(real_runner(process, services)) == "completed"
            result = client.get(
                "/v1/candidate-cases/" + event["subject"] + "/onboarding", headers=headers
            )
            assert result.status_code == 200
            assert all(step["status"] == "succeeded" for step in result.json()["steps"])
            assert len(result.json()["tasks"]) == 4
            if explicit_date:
                assert result.json()["start_date"] == start_date
                assert all(task["due_date"] == start_date for task in result.json()["tasks"])
            assert time.monotonic() - started < 30
    finally:
        broker.close()
        cleanup(process, services)
