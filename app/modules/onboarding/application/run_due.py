"""External calls happen between short, fenced database transactions."""

import asyncio
from datetime import UTC, datetime

from app.modules.onboarding.application.ports import Directory, Hris, SagaRepository
from app.modules.onboarding.domain.policy import STEP_POLICIES, AttemptTimeout


async def bounded(call, timeout):
    try:
        return await asyncio.wait_for(call, timeout=timeout)
    except TimeoutError:
        raise AttemptTimeout() from None


class DueStepRunner:
    def __init__(
        self,
        repository: SagaRepository,
        hris: Hris,
        directory: Directory,
        *,
        clock=lambda: datetime.now(UTC),
        execute=bounded,
    ):
        self.repository, self.hris, self.directory = repository, hris, directory
        self.clock, self.execute = clock, execute

    def run_one(self):
        claim = self.repository.claim(self.clock())
        if claim is None:
            return False
        error, ref = None, None
        try:
            if claim.step == "create_employee":
                call = (
                    self.hris.delete_employee(claim.saga_id)
                    if claim.compensation
                    else self.hris.upsert_employee(claim.saga_id, claim.person)
                )
            else:
                call = (
                    self.directory.delete_user(claim.case_id, claim.saga_id)
                    if claim.compensation
                    else self.directory.provision_user(claim.case_id, claim.saga_id, claim.person)
                )
            ref = asyncio.run(self.execute(call, STEP_POLICIES[claim.step].timeout))
        except Exception as exc:
            # Record only a bounded class/code, never external exception text.
            error = exc
        self.repository.record(claim, self.clock(), external_ref=ref, error=error)
        return True

    def run_due(self, limit=20):
        count = 0
        for _ in range(limit):
            if not self.run_one():
                break
            count += 1
        return count
