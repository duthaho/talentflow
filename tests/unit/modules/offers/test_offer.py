import pytest

from app.modules.offers.domain.approval_policy import ApprovalPolicy
from app.modules.offers.domain.offer import InvalidOfferApprovalError, Offer
from app.modules.workflow.domain.candidate_state_machine import CandidateStage


def test_first_approval_advances_offer_without_transitioning_candidate() -> None:
    offer = Offer.pending(tenant_id="tenant", candidate_case_id="candidate")

    result = offer.decide(
        decision="approved", actor_role="hiring_manager", policy=ApprovalPolicy.standard()
    )

    assert result.offer.status == "pending_approval"
    assert result.offer.approval_step == 2
    assert result.offer.version == 2
    assert result.candidate_target_stage is None


def test_final_approval_transitions_candidate_to_approved() -> None:
    offer = Offer("offer", "tenant", "candidate", "pending_approval", 2, 2)

    result = offer.decide(
        decision="approved", actor_role="tenant_admin", policy=ApprovalPolicy.standard()
    )

    assert result.offer.status == "approved"
    assert result.candidate_target_stage is CandidateStage.OFFER_APPROVED


def test_approval_rejects_an_actor_out_of_order() -> None:
    offer = Offer.pending(tenant_id="tenant", candidate_case_id="candidate")

    with pytest.raises(InvalidOfferApprovalError, match="required approver"):
        offer.decide(
            decision="approved", actor_role="tenant_admin", policy=ApprovalPolicy.standard()
        )
