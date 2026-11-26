from datetime import UTC
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status

from app.api.schemas import (
    CandidateCaseDetailResponse,
    CandidateCaseResponse,
    CandidateListItem,
    CandidateListResponse,
    CreateCandidateCaseRequest,
    TransitionCandidateCaseRequest,
)
from app.modules.candidates.application.create_candidate import (
    CandidateEmailAlreadyExistsError,
    CreateCandidateCommand,
    CreateCandidateHandler,
    RequisitionNotFoundError,
)
from app.modules.candidates.application.list_candidates import (
    ListCandidatesHandler,
    ListCandidatesQuery,
)
from app.modules.candidates.application.transition_candidate import (
    ApprovedOfferRequiredError,
    CandidateNotFoundError,
    ConcurrencyConflictError,
    OfferStageManagedByOfferFlowError,
    TransitionCandidateCommand,
    TransitionCandidateHandler,
)
from app.modules.candidates.infrastructure.models import CandidateCase
from app.modules.candidates.infrastructure.sqlalchemy_repository import (
    SqlAlchemyAuditRecorder,
    SqlAlchemyCandidateRepository,
    SqlAlchemyRequisitionRepository,
    SqlAlchemyUnitOfWork,
)
from app.modules.identity.security import ActorContext, require
from app.modules.offers.infrastructure.sqlalchemy_repository import SqlAlchemyOfferRepository
from app.modules.workflow.domain.candidate_state_machine import InvalidTransitionError
from app.shared.database import SessionDep
from app.shared.observability import command_conflicts

router = APIRouter()


@router.get("/v1/candidate-cases", response_model=CandidateListResponse)
def list_candidate_cases(
    session: SessionDep,
    actor: ActorContext = Depends(require("tenant:read")),
    stage: str | None = None,
    requisition_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> CandidateListResponse:
    page = ListCandidatesHandler(SqlAlchemyCandidateRepository(session)).handle(
        ListCandidatesQuery(
            tenant_id=actor.tenant_id,
            stage=stage,
            requisition_id=requisition_id,
            cursor=cursor,
            limit=limit,
        )
    )
    return CandidateListResponse(
        items=[CandidateListItem(**item.__dict__) for item in page.items],
        next_cursor=page.next_cursor,
        total=page.total,
    )


@router.get("/v1/candidate-cases/{candidate_case_id}", response_model=CandidateCaseDetailResponse)
def get_candidate_case(
    candidate_case_id: str,
    response: Response,
    session: SessionDep,
    actor: ActorContext = Depends(require("tenant:read")),
) -> CandidateCaseDetailResponse:
    record = session.get(CandidateCase, candidate_case_id)
    if record is None or record.tenant_id != actor.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Candidate case not found"
        )
    response.headers["Cache-Control"] = "private, no-store"
    detail = CandidateCaseDetailResponse.model_validate(record, from_attributes=True)
    created_at = detail.created_at
    if created_at.tzinfo is None:
        detail = detail.model_copy(update={"created_at": created_at.replace(tzinfo=UTC)})
    return detail


@router.post(
    "/v1/candidate-cases", response_model=CandidateCaseResponse, status_code=status.HTTP_201_CREATED
)
def create_candidate_case(
    payload: CreateCandidateCaseRequest,
    request: Request,
    session: SessionDep,
    actor: ActorContext = Depends(require("candidate:create")),
    correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
) -> CandidateCaseResponse:
    try:
        created = CreateCandidateHandler(
            candidates=SqlAlchemyCandidateRepository(session),
            requisitions=SqlAlchemyRequisitionRepository(session),
            audit=SqlAlchemyAuditRecorder(session),
            unit_of_work=SqlAlchemyUnitOfWork(session),
        ).handle(
            CreateCandidateCommand(
                tenant_id=actor.tenant_id,
                requisition_id=payload.requisition_id,
                first_name=payload.first_name,
                last_name=payload.last_name,
                email=payload.email,
                actor_id=actor.actor_id,
                correlation_id=correlation_id
                or request.headers.get("X-Request-Id")
                or str(uuid4()),
            )
        )
    except RequisitionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found"
        ) from error
    except CandidateEmailAlreadyExistsError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return CandidateCaseResponse(
        id=created.candidate.id,
        requisition_id=created.candidate.requisition_id,
        first_name=created.first_name,
        last_name=created.last_name,
        email=created.email,
        stage=created.candidate.stage.value,
        version=created.candidate.version,
    )


@router.patch("/v1/candidate-cases/{candidate_case_id}/stage", response_model=CandidateCaseResponse)
def transition_candidate_case_stage(
    candidate_case_id: str,
    payload: TransitionCandidateCaseRequest,
    request: Request,
    session: SessionDep,
    actor: ActorContext = Depends(require("candidate:transition")),
    correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
) -> CandidateCaseResponse:
    try:
        transitioned = TransitionCandidateHandler(
            repository=SqlAlchemyCandidateRepository(session),
            approved_offers=SqlAlchemyOfferRepository(session),
            audit=SqlAlchemyAuditRecorder(session),
            unit_of_work=SqlAlchemyUnitOfWork(session),
        ).handle(
            TransitionCandidateCommand(
                candidate_id=candidate_case_id,
                tenant_id=actor.tenant_id,
                target_stage=payload.target_stage,
                expected_version=payload.expected_version,
                actor_id=actor.actor_id,
                correlation_id=correlation_id
                or request.headers.get("X-Request-Id")
                or str(uuid4()),
            )
        )
    except CandidateNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Candidate case not found"
        ) from error
    except ConcurrencyConflictError as error:
        command_conflicts.labels("candidate_case").inc()
        current = session.get(CandidateCase, candidate_case_id)
        if current is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Candidate case not found"
            ) from error
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "detail": "Candidate case has changed; refresh and retry",
                "problem_type": "version-conflict",
                "current_version": current.version,
            },
        ) from error
    except (
        ApprovedOfferRequiredError,
        InvalidTransitionError,
        OfferStageManagedByOfferFlowError,
        ValueError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    record = session.get(CandidateCase, transitioned.id)
    assert record is not None
    return CandidateCaseResponse(
        id=record.id,
        requisition_id=record.requisition_id,
        first_name=record.first_name,
        last_name=record.last_name,
        email=record.email,
        stage=transitioned.stage.value,
        version=transitioned.version,
    )
