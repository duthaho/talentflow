from app.modules.candidates.application.transition_candidate import (
    TransitionCandidateCommand,
    TransitionCandidateHandler,
)
from app.modules.candidates.domain.candidate_case import CandidateCase
from app.modules.workflow.domain.candidate_state_machine import CandidateStage


class FakeRepository:
    def __init__(self, candidate: CandidateCase | None):
        self.candidate = candidate

    def get(self, *, candidate_id: str, tenant_id: str) -> CandidateCase | None:
        return self.candidate

    def transition(self, *, candidate: CandidateCase, expected_version: int) -> bool:
        self.candidate = candidate
        return True


class FakeAudit:
    transitioned: CandidateCase | None = None

    def candidate_stage_transitioned(self, *, candidate: CandidateCase, **_: object) -> None:
        self.transitioned = candidate


class FakeUnitOfWork:
    committed = False

    def commit(self) -> None:
        self.committed = True


def test_transition_handler_applies_domain_transition_and_commits() -> None:
    repository = FakeRepository(
        CandidateCase("candidate", "tenant", "req", CandidateStage.APPLIED, 1)
    )
    audit = FakeAudit()
    unit_of_work = FakeUnitOfWork()
    result = TransitionCandidateHandler(
        repository=repository, audit=audit, unit_of_work=unit_of_work
    ).handle(
        TransitionCandidateCommand(
            "candidate", "tenant", "screening", 1, "recruiter", "correlation"
        )
    )
    assert result.stage is CandidateStage.SCREENING
    assert result.version == 2
    assert audit.transitioned is result
    assert unit_of_work.committed
