from __future__ import annotations

from dataclasses import dataclass

from app.modules.offers.application.ports import (
    CandidateWorkflowRepository,
    OfferRepository,
    UnitOfWork,
)
from app.modules.offers.domain.offer import Offer
from app.modules.workflow.domain.candidate_state_machine import CandidateStage


class CandidateNotEligibleForOfferError(ValueError):
    pass


class OfferAlreadyExistsError(RuntimeError):
    pass


@dataclass(frozen=True)
class CreateOfferCommand:
    tenant_id: str
    candidate_case_id: str
    title: str
    annual_salary: int
    currency: str
    actor_id: str


class CreateOfferHandler:
    def __init__(
        self,
        *,
        candidates: CandidateWorkflowRepository,
        offers: OfferRepository,
        unit_of_work: UnitOfWork,
    ):
        self._candidates = candidates
        self._offers = offers
        self._unit_of_work = unit_of_work

    def handle(self, command: CreateOfferCommand) -> Offer:
        candidate = self._candidates.get(
            candidate_id=command.candidate_case_id, tenant_id=command.tenant_id
        )
        if candidate is None or candidate.stage != CandidateStage.INTERVIEWING:
            raise CandidateNotEligibleForOfferError(
                "Candidate must be interviewing before an offer is created"
            )
        offer = Offer.pending(tenant_id=command.tenant_id, candidate_case_id=candidate.id)
        transitioned_candidate = candidate.transition(CandidateStage.OFFER_PENDING_APPROVAL)
        if not self._candidates.transition(
            candidate=transitioned_candidate, expected_version=candidate.version
        ):
            raise OfferAlreadyExistsError("Candidate case has changed; refresh and retry")
        self._offers.add(
            offer=offer,
            title=command.title,
            annual_salary=command.annual_salary,
            currency=command.currency,
            created_by=command.actor_id,
        )
        self._unit_of_work.commit()
        return offer
