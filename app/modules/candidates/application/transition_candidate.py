from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.modules.candidates.application.ports import (
    ApprovedOfferRepository,
    AuditRecorder,
    CandidateRepository,
    UnitOfWork,
)
from app.modules.candidates.domain.candidate_case import CandidateCase
from app.modules.candidates.domain.start_date import validate_start_date
from app.modules.workflow.domain.candidate_state_machine import CandidateStage
from app.shared.concurrency import resolve_expected_version


class CandidateNotFoundError(LookupError):
    pass


class ConcurrencyConflictError(RuntimeError):
    pass


class OfferStageManagedByOfferFlowError(ValueError):
    pass


class ApprovedOfferRequiredError(ValueError):
    pass


@dataclass(frozen=True)
class TransitionCandidateCommand:
    candidate_id: str
    tenant_id: str
    target_stage: str
    expected_version: int | None
    actor_id: str
    correlation_id: str
    if_match: tuple[str, ...] | None = None
    start_date: date | None = None


class TransitionCandidateHandler:
    def __init__(
        self,
        *,
        repository: CandidateRepository,
        approved_offers: ApprovedOfferRepository,
        audit: AuditRecorder,
        unit_of_work: UnitOfWork,
    ):
        self._repository = repository
        self._approved_offers = approved_offers
        self._audit = audit
        self._unit_of_work = unit_of_work

    def handle(self, command: TransitionCandidateCommand) -> CandidateCase:
        candidate = self._repository.get(
            candidate_id=command.candidate_id, tenant_id=command.tenant_id
        )
        if candidate is None:
            raise CandidateNotFoundError(command.candidate_id)
        expected_version = resolve_expected_version(
            current_version=candidate.version,
            expected_version=command.expected_version,
            if_match=command.if_match,
        )
        if candidate.version != expected_version:
            raise ConcurrencyConflictError(command.candidate_id)
        target_stage = CandidateStage(command.target_stage)
        if target_stage in {
            CandidateStage.OFFER_PENDING_APPROVAL,
            CandidateStage.OFFER_APPROVED,
            CandidateStage.OFFER_REJECTED,
        }:
            raise OfferStageManagedByOfferFlowError(
                "Offer stages can only be changed through the offers flow"
            )
        if (
            candidate.stage is CandidateStage.OFFER_APPROVED
            and target_stage is CandidateStage.HIRED
            and not self._approved_offers.has_approved_offer(
                candidate_id=candidate.id, tenant_id=command.tenant_id
            )
        ):
            raise ApprovedOfferRequiredError(
                "An approved offer is required before hiring a candidate"
            )
        validate_start_date(command.target_stage, command.start_date, datetime.now(UTC).date())
        transitioned = candidate.transition(target_stage, command.start_date)
        if not self._repository.transition(
            candidate=transitioned, expected_version=expected_version
        ):
            raise ConcurrencyConflictError(command.candidate_id)
        self._audit.candidate_stage_transitioned(
            candidate=transitioned,
            prior_stage=candidate.stage.value,
            actor_id=command.actor_id,
            correlation_id=command.correlation_id,
        )
        self._unit_of_work.commit()
        return transitioned
