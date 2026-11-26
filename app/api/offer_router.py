from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.schemas import (
    ApproveOfferRequest,
    CreateOfferRequest,
    OfferDecisionResponse,
    OfferDetailResponse,
    OfferPageResponse,
    OfferResponse,
    OfferSummaryResponse,
)
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
from app.modules.offers.application.get_offer import GetOfferHandler, GetOfferQuery
from app.modules.offers.application.list_offers import ListOffersHandler, ListOffersQuery
from app.modules.offers.application.views import OfferView
from app.modules.offers.domain.approval_policy import ApprovalPolicy
from app.modules.offers.domain.offer import InvalidOfferReasonError
from app.modules.offers.domain.offer import Offer as DomainOffer
from app.modules.offers.infrastructure.models import Offer
from app.modules.offers.infrastructure.sqlalchemy_repository import (
    SqlAlchemyOfferRepository,
    SqlAlchemyUnitOfWork,
)
from app.modules.workflow.domain.candidate_state_machine import CandidateStage
from app.shared.database import SessionDep
from app.shared.observability import command_conflicts

router = APIRouter()


def _summary(*, view: OfferView, actor_role: str, policy: ApprovalPolicy) -> OfferSummaryResponse:
    offer = DomainOffer(
        view.id,
        "",
        view.candidate_case_id,
        view.status,
        view.approval_step,
        view.version,
    )
    awaiting_role = (
        policy.required_role(view.approval_step) if view.status == "pending_approval" else None
    )
    return OfferSummaryResponse(
        **view.__dict__,
        awaiting_role=awaiting_role,
        can_decide=offer.can_be_decided_by(actor_role=actor_role, policy=policy),
    )


@router.get("/v1/offers", response_model=OfferPageResponse)
def list_offers(
    response: Response,
    session: SessionDep,
    actor: ActorContext = Depends(require("tenant:read")),
    awaiting: Literal["me"] | None = None,
    candidate_case_id: str | None = Query(default=None, max_length=64),
    status_filter: Literal["pending_approval", "approved", "rejected"] | None = Query(
        default=None, alias="status"
    ),
    cursor: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=25, ge=1, le=100),
) -> OfferPageResponse:
    policy = ApprovalPolicy.standard()
    page = ListOffersHandler(offers=SqlAlchemyOfferRepository(session), policy=policy).handle(
        ListOffersQuery(
            tenant_id=actor.tenant_id,
            actor_role=actor.role,
            awaiting_me=awaiting == "me",
            candidate_case_id=candidate_case_id,
            status=status_filter,
            cursor=cursor,
            limit=limit,
        )
    )
    response.headers["Cache-Control"] = "private, no-store"
    return OfferPageResponse(
        items=[_summary(view=item, actor_role=actor.role, policy=policy) for item in page.items],
        next_cursor=page.next_cursor,
        total=page.total,
    )


@router.get("/v1/offers/{offer_id}", response_model=OfferDetailResponse)
def get_offer(
    offer_id: str,
    response: Response,
    session: SessionDep,
    actor: ActorContext = Depends(require("tenant:read")),
) -> OfferDetailResponse:
    try:
        detail = GetOfferHandler(
            offers=SqlAlchemyOfferRepository(session), policy=ApprovalPolicy.standard()
        ).handle(GetOfferQuery(tenant_id=actor.tenant_id, offer_id=offer_id, actor_role=actor.role))
    except OfferNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Offer not found"
        ) from error
    response.headers["Cache-Control"] = "private, no-store"
    return OfferDetailResponse(
        **detail.offer.__dict__,
        awaiting_role=detail.awaiting_role,
        can_decide=detail.can_decide,
        decisions=[OfferDecisionResponse(**decision.__dict__) for decision in detail.decisions],
    )


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
                reason=payload.reason,
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
    except InvalidOfferReasonError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
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
