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


def test_transition_handler_applies_domain_transition() -> None:
    repository = FakeRepository(
        CandidateCase("candidate", "tenant", "req", CandidateStage.APPLIED, 1)
    )
    result = TransitionCandidateHandler(repository).handle(
        TransitionCandidateCommand("candidate", "tenant", "screening", 1)
    )
    assert result.stage is CandidateStage.SCREENING
    assert result.version == 2
