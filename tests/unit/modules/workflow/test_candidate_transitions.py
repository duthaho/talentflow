import pytest

from app.modules.workflow.domain.candidate_state_machine import (
    CandidateStage,
    InvalidTransitionError,
    transition_to,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (CandidateStage.APPLIED, CandidateStage.SCREENING),
        (CandidateStage.SCREENING, CandidateStage.INTERVIEWING),
        (CandidateStage.INTERVIEWING, CandidateStage.OFFER_PENDING_APPROVAL),
        (CandidateStage.OFFER_PENDING_APPROVAL, CandidateStage.OFFER_APPROVED),
        (CandidateStage.OFFER_APPROVED, CandidateStage.HIRED),
        (CandidateStage.SCREENING, CandidateStage.REJECTED),
        (CandidateStage.OFFER_REJECTED, CandidateStage.WITHDRAWN),
    ],
)
def test_allows_valid_candidate_stage_transition(
    current: CandidateStage, target: CandidateStage
) -> None:
    assert transition_to(current, target) is target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (CandidateStage.APPLIED, CandidateStage.HIRED),
        (CandidateStage.INTERVIEWING, CandidateStage.APPLIED),
        (CandidateStage.HIRED, CandidateStage.SCREENING),
        (CandidateStage.REJECTED, CandidateStage.INTERVIEWING),
    ],
)
def test_rejects_invalid_or_terminal_candidate_stage_transition(
    current: CandidateStage, target: CandidateStage
) -> None:
    with pytest.raises(InvalidTransitionError):
        transition_to(current, target)
