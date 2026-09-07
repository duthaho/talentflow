from __future__ import annotations

from enum import StrEnum


class CandidateStage(StrEnum):
    APPLIED = "applied"
    SCREENING = "screening"
    INTERVIEWING = "interviewing"
    OFFER_PENDING_APPROVAL = "offer_pending_approval"
    OFFER_APPROVED = "offer_approved"
    OFFER_REJECTED = "offer_rejected"
    HIRED = "hired"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class InvalidTransitionError(ValueError):
    pass


_ALLOWED_TRANSITIONS: dict[CandidateStage, frozenset[CandidateStage]] = {
    CandidateStage.APPLIED: frozenset(
        {CandidateStage.SCREENING, CandidateStage.REJECTED, CandidateStage.WITHDRAWN}
    ),
    CandidateStage.SCREENING: frozenset(
        {CandidateStage.INTERVIEWING, CandidateStage.REJECTED, CandidateStage.WITHDRAWN}
    ),
    CandidateStage.INTERVIEWING: frozenset(
        {CandidateStage.OFFER_PENDING_APPROVAL, CandidateStage.REJECTED, CandidateStage.WITHDRAWN}
    ),
    CandidateStage.OFFER_PENDING_APPROVAL: frozenset(
        {CandidateStage.OFFER_APPROVED, CandidateStage.OFFER_REJECTED, CandidateStage.WITHDRAWN}
    ),
    CandidateStage.OFFER_APPROVED: frozenset({CandidateStage.HIRED, CandidateStage.WITHDRAWN}),
    CandidateStage.OFFER_REJECTED: frozenset({CandidateStage.REJECTED, CandidateStage.WITHDRAWN}),
    CandidateStage.HIRED: frozenset(),
    CandidateStage.REJECTED: frozenset(),
    CandidateStage.WITHDRAWN: frozenset(),
}


def transition_to(current: CandidateStage, target: CandidateStage) -> CandidateStage:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidTransitionError(f"Invalid candidate stage transition: {current} -> {target}")
    return target
