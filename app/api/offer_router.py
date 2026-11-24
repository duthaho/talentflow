from fastapi import APIRouter, Depends, HTTPException, status

from app.api.schemas import ApproveOfferRequest, CreateOfferRequest, OfferResponse
from app.modules.candidates.infrastructure.sqlalchemy_repository import (
    SqlAlchemyCandidateRepository,
)
from app.modules.identity.security import ActorContext, require
from app.modules.offers.application.create_offer import (
    CandidateNotEligibleForOfferError,
    CreateOfferCommand,
    CreateOfferHandler,
    OfferAlreadyExistsError,
)
from app.modules.offers.application.decide_offer import (
    DecideOfferCommand,
    DecideOfferHandler,
    InvalidOfferApprovalError,
    OfferConcurrencyConflictError,
    OfferNotFoundError,
)
from app.modules.offers.domain.approval_policy import ApprovalPolicy
from app.modules.offers.infrastructure.models import Offer
from app.modules.offers.infrastructure.sqlalchemy_repository import (
    SqlAlchemyOfferRepository,
    SqlAlchemyUnitOfWork,
)
from app.modules.workflow.domain.candidate_state_machine import CandidateStage
from app.shared.database import SessionDep
from app.shared.observability import command_conflicts

router = APIRouter()


@router.post(
    "/v1/candidate-cases/{candidate_case_id}/offers",
    response_model=OfferResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_offer(
    candidate_case_id: str,
    payload: CreateOfferRequest,
    session: SessionDep,
    actor: ActorContext = Depends(require("candidate:transition")),
) -> OfferResponse:
    try:
        offer = CreateOfferHandler(
            candidates=SqlAlchemyCandidateRepository(session),
            offers=SqlAlchemyOfferRepository(session),
            unit_of_work=SqlAlchemyUnitOfWork(session),
        ).handle(
            CreateOfferCommand(
                tenant_id=actor.tenant_id,
                candidate_case_id=candidate_case_id,
                title=payload.title,
                annual_salary=payload.annual_salary,
                currency=payload.currency,
                actor_id=actor.actor_id,
            )
        )
    except (CandidateNotEligibleForOfferError, OfferAlreadyExistsError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return OfferResponse(
        id=offer.id,
        status=offer.status,
        approval_step=offer.approval_step,
        version=offer.version,
        candidate_stage=CandidateStage.OFFER_PENDING_APPROVAL.value,
    )


@router.post("/v1/offers/{offer_id}/approvals", response_model=OfferResponse)
def approve_offer(
    offer_id: str,
    payload: ApproveOfferRequest,
    session: SessionDep,
    actor: ActorContext = Depends(require("tenant:read")),
) -> OfferResponse:
    try:
        offer, candidate_stage = DecideOfferHandler(
            candidates=SqlAlchemyCandidateRepository(session),
            offers=SqlAlchemyOfferRepository(session),
            unit_of_work=SqlAlchemyUnitOfWork(session),
            policy=ApprovalPolicy.standard(),
        ).handle(
            DecideOfferCommand(
                offer_id=offer_id,
                tenant_id=actor.tenant_id,
                actor_id=actor.actor_id,
                actor_role=actor.role,
                decision=payload.decision,
                expected_version=payload.expected_version,
            )
        )
    except OfferNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Offer not found"
        ) from error
    except OfferConcurrencyConflictError as error:
        command_conflicts.labels("offer").inc()
        current = session.get(Offer, offer_id)
        if current is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Offer not found"
            ) from error
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "detail": "Offer has changed; refresh and retry",
                "problem_type": "version-conflict",
                "current_version": current.version,
            },
        ) from error
    except InvalidOfferApprovalError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    return OfferResponse(
        id=offer.id,
        status=offer.status,
        approval_step=offer.approval_step,
        version=offer.version,
        candidate_stage=candidate_stage,
    )
