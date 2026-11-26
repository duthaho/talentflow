from unittest.mock import Mock

import pytest

from app.modules.candidates.application.transition_candidate import (
    TransitionCandidateCommand,
    TransitionCandidateHandler,
)
from app.modules.candidates.domain.candidate_case import CandidateCase
from app.modules.offers.application.decide_offer import DecideOfferCommand, DecideOfferHandler
from app.modules.offers.domain.approval_policy import ApprovalPolicy
from app.modules.offers.domain.offer import Offer
from app.modules.workflow.domain.candidate_state_machine import CandidateStage
from app.shared.concurrency import (
    InvalidVersionPreconditionError,
    VersionPreconditionFailedError,
    VersionPreconditionRequiredError,
)


@pytest.mark.parametrize("aggregate", ["candidate", "offer"])
@pytest.mark.parametrize(
    "version,condition,error",
    [
        (None, None, VersionPreconditionRequiredError),
        (None, ("2",), VersionPreconditionFailedError),
        (1, ("2",), InvalidVersionPreconditionError),
    ],
)
def test_preconditions_fail_before_writes_or_effects(aggregate, version, condition, error):
    repository, audit, candidates, unit_of_work = Mock(), Mock(), Mock(), Mock()
    if aggregate == "candidate":
        repository.get.return_value = CandidateCase(
            "case", "tenant", "req", CandidateStage.APPLIED, 1
        )
        handler = TransitionCandidateHandler(
            repository=repository, approved_offers=Mock(), audit=audit, unit_of_work=unit_of_work
        )
        command = TransitionCandidateCommand(
            "case", "tenant", "screening", version, "actor", "ref", condition
        )
    else:
        repository.get.return_value = Offer("offer", "tenant", "case", "pending_approval", 1, 1)
        handler = DecideOfferHandler(
            candidates=candidates,
            offers=repository,
            unit_of_work=unit_of_work,
            policy=ApprovalPolicy.standard(),
        )
        command = DecideOfferCommand(
            "offer", "tenant", "actor", "hiring_manager", "approved", version, if_match=condition
        )
    with pytest.raises(error):
        handler.handle(command)
    repository.transition.assert_not_called()
    repository.update.assert_not_called()
    repository.record_decision.assert_not_called()
    repository.record_outbox_event.assert_not_called()
    assert not audit.mock_calls
    assert not candidates.mock_calls
    unit_of_work.commit.assert_not_called()
