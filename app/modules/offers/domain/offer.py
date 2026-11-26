from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.modules.offers.domain.approval_policy import ApprovalPolicy
from app.modules.workflow.domain.candidate_state_machine import CandidateStage


class InvalidOfferApprovalError(ValueError):
    pass


class InvalidOfferReasonError(InvalidOfferApprovalError):
    pass


@dataclass(frozen=True)
class Offer:
    id: str
    tenant_id: str
    candidate_case_id: str
    status: str
    approval_step: int
    version: int

    @classmethod
    def pending(cls, *, tenant_id: str, candidate_case_id: str) -> Offer:
        return cls(
            id=str(uuid4()),
            tenant_id=tenant_id,
            candidate_case_id=candidate_case_id,
            status="pending_approval",
            approval_step=1,
            version=1,
        )

    def can_be_decided_by(self, *, actor_role: str, policy: ApprovalPolicy) -> bool:
        return self.status == "pending_approval" and actor_role == policy.required_role(
            self.approval_step
        )

    def decide(
        self,
        *,
        decision: str,
        actor_role: str,
        policy: ApprovalPolicy,
        reason: str | None = None,
    ) -> OfferDecision:
        if decision not in {"approved", "rejected"}:
            raise InvalidOfferApprovalError("Unsupported offer approval decision")
        if not self.can_be_decided_by(actor_role=actor_role, policy=policy):
            raise InvalidOfferApprovalError("Actor is not the required approver")
        normalized_reason = reason.strip() if reason is not None else None
        if normalized_reason == "":
            normalized_reason = None
        if normalized_reason is not None and len(normalized_reason) > 500:
            raise InvalidOfferReasonError("Offer approval reason must be at most 500 characters")
        if decision == "rejected" and normalized_reason is None:
            raise InvalidOfferReasonError("A rejection requires a reason")

        if decision == "rejected":
            updated = Offer(
                id=self.id,
                tenant_id=self.tenant_id,
                candidate_case_id=self.candidate_case_id,
                status="rejected",
                approval_step=self.approval_step,
                version=self.version + 1,
            )
            return OfferDecision(
                updated,
                CandidateStage.OFFER_REJECTED,
                self.approval_step,
                decision,
                normalized_reason,
            )

        final_step = policy.steps[-1].number
        if self.approval_step == final_step:
            updated = Offer(
                id=self.id,
                tenant_id=self.tenant_id,
                candidate_case_id=self.candidate_case_id,
                status="approved",
                approval_step=self.approval_step,
                version=self.version + 1,
            )
            return OfferDecision(
                updated,
                CandidateStage.OFFER_APPROVED,
                self.approval_step,
                decision,
                normalized_reason,
            )

        updated = Offer(
            id=self.id,
            tenant_id=self.tenant_id,
            candidate_case_id=self.candidate_case_id,
            status=self.status,
            approval_step=self.approval_step + 1,
            version=self.version + 1,
        )
        return OfferDecision(updated, None, self.approval_step, decision, normalized_reason)


@dataclass(frozen=True)
class OfferDecision:
    offer: Offer
    candidate_target_stage: CandidateStage | None
    step: int
    decision: str
    reason: str | None
