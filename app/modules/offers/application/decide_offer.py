from __future__ import annotations

from dataclasses import dataclass

from app.modules.offers.application.ports import (
    CandidateWorkflowRepository,
    OfferRepository,
    UnitOfWork,
)
from app.modules.offers.domain.approval_policy import ApprovalPolicy
from app.modules.offers.domain.offer import InvalidOfferApprovalError, Offer


class OfferNotFoundError(LookupError):
    pass


class OfferConcurrencyConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class DecideOfferCommand:
    offer_id: str
    tenant_id: str
    actor_id: str
    actor_role: str
    decision: str
    expected_version: int


class DecideOfferHandler:
    def __init__(
        self,
        *,
        candidates: CandidateWorkflowRepository,
        offers: OfferRepository,
        unit_of_work: UnitOfWork,
        policy: ApprovalPolicy,
    ):
        self._candidates = candidates
        self._offers = offers
        self._unit_of_work = unit_of_work
        self._policy = policy

    def handle(self, command: DecideOfferCommand) -> tuple[Offer, str]:
        offer = self._offers.get(offer_id=command.offer_id, tenant_id=command.tenant_id)
        if offer is None:
            raise OfferNotFoundError(command.offer_id)
        if offer.version != command.expected_version:
            raise OfferConcurrencyConflictError(command.offer_id)
        outcome = offer.decide(
            decision=command.decision, actor_role=command.actor_role, policy=self._policy
        )
        if not self._offers.update(offer=outcome.offer, expected_version=command.expected_version):
            raise OfferConcurrencyConflictError(command.offer_id)
        candidate_stage = "offer_pending_approval"
        if outcome.candidate_target_stage is not None:
            candidate = self._candidates.get(
                candidate_id=offer.candidate_case_id, tenant_id=command.tenant_id
            )
            if candidate is None or not self._candidates.transition(
                candidate=candidate.transition(outcome.candidate_target_stage),
                expected_version=candidate.version,
            ):
                raise OfferConcurrencyConflictError(command.offer_id)
            candidate_stage = outcome.candidate_target_stage.value
        self._offers.record_decision(
            offer=offer,
            step=outcome.step,
            actor_id=command.actor_id,
            decision=outcome.decision,
        )
        self._offers.record_outbox_event(
            offer=offer, actor_id=command.actor_id, decision=outcome.decision
        )
        self._unit_of_work.commit()
        return outcome.offer, candidate_stage


__all__ = [
    "DecideOfferCommand",
    "DecideOfferHandler",
    "InvalidOfferApprovalError",
    "OfferConcurrencyConflictError",
    "OfferNotFoundError",
]
