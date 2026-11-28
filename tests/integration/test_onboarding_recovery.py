"""Ambiguous-effect regressions: inspect both external systems before cleanup."""

import asyncio
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from test_onboarding import advance
from test_onboarding import process as process
from test_onboarding_api import api as api
from test_onboarding_services import cleanup
from test_onboarding_services import services as services

from app.modules.candidates.persistence import CandidateCase
from app.modules.onboarding.application.run_due import DueStepRunner
from app.modules.onboarding.domain.policy import AttemptTimeout, TransientStepError
from app.modules.onboarding.infrastructure.consumer import OnboardingConsumer
from app.modules.onboarding.infrastructure.models import Saga, Step


class AmbiguousProvisioning:
    """The first response is lost after the real effect; later calls fail with 5xx."""

    def __init__(self, hris, directory, step):
        self.hris, self.directory, self.step = hris, directory, step
        self.calls = 0

    async def invoke(self, step, call):
        if step != self.step:
            return await call()
        self.calls += 1
        if self.calls == 1:
            await call()
            raise AttemptTimeout()
        raise TransientStepError()

    async def upsert_employee(self, key, person):
        return await self.invoke("create_employee", lambda: self.hris.upsert_employee(key, person))

    async def delete_employee(self, key):
        return await self.hris.delete_employee(key)

    async def provision_user(self, case, saga, person):
        return await self.invoke(
            "provision_account", lambda: self.directory.provision_user(case, saga, person)
        )

    async def delete_user(self, case, saga):
        return await self.directory.delete_user(case, saga)


def external_state(services, saga):
    """Query actual records, rather than relying on adapter call history or owned()."""
    response = httpx.get(
        services[0].hris_stub_url + "/v1/employees/" + saga.id,
        headers={"Authorization": "Bearer " + services[0].hris_stub_token.get_secret_value()},
    )
    assert response.status_code in {200, 404}

    async def users():
        async with httpx.AsyncClient() as client:
            response = await services[2].call(
                client,
                "GET",
                "/users",
                params={"username": "tf-" + saga.candidate_case_id, "exact": "true"},
            )
            assert response.status_code == 200
            return response.json()

    return response.status_code == 200, asyncio.run(users())


@pytest.mark.parametrize("step", ["create_employee", "provision_account"])
@pytest.mark.parametrize("ending", ["exhausted", "deadline", "cancel", "erased"])
def test_real_ambiguous_effect_cleanup(process, services, api, step, ending):
    sessions, repo, _, _, now, event = process
    transport = AmbiguousProvisioning(services[1], services[2], step)
    runner = DueStepRunner(repo, transport, transport, clock=lambda: now[0])
    controlled = list(process)
    controlled[2] = runner
    try:
        if step == "provision_account":
            assert runner.run_one()  # employee committed
        assert runner.run_one()  # remote effect committed, response timed out
        with sessions() as session:
            saga = session.scalar(select(Saga))
            failed_step = session.scalar(select(Step).where(Step.step == step))
            assert failed_step.status == "retry_wait"
            assert failed_step.last_error == "AttemptTimeout" and failed_step.attempts == 1
            deadline = failed_step.deadline_at
        employee_exists, accounts = external_state(services, saga)
        assert employee_exists
        assert len(accounts) == int(step == "provision_account")

        if ending == "deadline":
            now[0] = deadline
        elif ending == "cancel":
            response = api[1].post(
                "/v1/onboarding-sagas/" + saga.id + "/cancel",
                headers={**api[2], "If-Match": f'"{saga.version}"'},
            )
            assert response.status_code == 202, response.text
        elif ending == "erased":
            with sessions.begin() as session:
                session.get(CandidateCase, saga.candidate_case_id).anonymized_at = now[0]
            consumer = OnboardingConsumer(sessions, None, repo, None, clock=lambda: now[0])
            assert (
                consumer.apply({**event, "id": str(uuid4()), "type": "candidate_case.erased.v1"})
                == "erased"
            )

        assert advance(controlled) == (
            "cancelled" if ending in {"cancel", "erased"} else "compensated"
        )
        # Assert before finally's safety cleanup: terminal success must mean no PII remains.
        employee_exists, accounts = external_state(services, saga)
        assert not employee_exists, "HRIS employee survived the terminal compensation"
        assert accounts == [], "Keycloak account survived the terminal compensation"
        with sessions() as session:
            failed_step = session.scalar(select(Step).where(Step.step == step))
            assert failed_step.compensation_status == "done"
            assert session.get(CandidateCase, saga.candidate_case_id).stage == "hired"
            if ending == "exhausted":
                assert failed_step.attempts == 5 and transport.calls == 5
    finally:
        cleanup(process, services)


def test_real_directory_conflict_cleanup_preserves_foreign_account(process, services):
    with process[0]() as session:
        saga = session.scalar(select(Saga))
        candidate = session.get(CandidateCase, saga.candidate_case_id)
        person = {
            "tenant_id": saga.tenant_id,
            "first_name": candidate.first_name,
            "last_name": candidate.last_name,
            "email": candidate.email,
        }
    foreign_saga = str(uuid4())
    foreign_user = asyncio.run(
        services[2].provision_user(saga.candidate_case_id, foreign_saga, person)
    )
    controlled = list(process)
    controlled[2] = DueStepRunner(process[1], services[1], services[2], clock=lambda: process[4][0])
    try:
        assert advance(controlled) == "compensated"
        employee_exists, accounts = external_state(services, saga)
        assert not employee_exists
        assert len(accounts) == 1 and accounts[0]["id"] == foreign_user
        assert accounts[0]["attributes"]["onboarding_saga_id"] == [foreign_saga]
        with process[0]() as session:
            failed_step = session.scalar(select(Step).where(Step.step == "provision_account"))
            assert failed_step.attempts == 1 and failed_step.compensation_status == "done"
    finally:
        asyncio.run(services[2].delete_user(saga.candidate_case_id, foreign_saga))
        cleanup(process, services)
