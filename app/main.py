from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.schemas import (
    ApproveOfferRequest,
    AuditEventResponse,
    CandidateCaseResponse,
    CandidateListItem,
    CandidateListResponse,
    CreateCandidateCaseRequest,
    CreateInterviewRequest,
    CreateOfferRequest,
    CreateRequisitionRequest,
    CreateTenantRequest,
    FeedbackResponse,
    InterviewResponse,
    OfferResponse,
    RequisitionResponse,
    SubmitFeedbackRequest,
    TenantResponse,
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
    CandidateNotFoundError,
    ConcurrencyConflictError,
    TransitionCandidateCommand,
    TransitionCandidateHandler,
)
from app.modules.candidates.infrastructure.sqlalchemy_repository import (
    SqlAlchemyAuditRecorder,
    SqlAlchemyCandidateRepository,
    SqlAlchemyRequisitionRepository,
)
from app.modules.candidates.infrastructure.sqlalchemy_repository import (
    SqlAlchemyUnitOfWork as SqlAlchemyCandidateUnitOfWork,
)
from app.modules.identity.security import ActorContext, require
from app.modules.interviews.domain.feedback import (
    FeedbackAlreadySubmittedError,
    InterviewerNotAssignedError,
    assert_feedback_can_be_submitted,
)
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
from app.modules.offers.infrastructure.sqlalchemy_repository import (
    SqlAlchemyOfferRepository,
    SqlAlchemyUnitOfWork,
)
from app.modules.workflow.domain.candidate_state_machine import (
    CandidateStage,
    InvalidTransitionError,
    transition_to,
)
from app.shared.database import SessionDep, build_engine
from app.shared.models import (
    AuditEvent,
    Base,
    CandidateCase,
    Interview,
    InterviewFeedback,
    Membership,
    Requisition,
    Tenant,
    User,
)
from app.shared.settings import settings


def create_app(database_url: str | None = None) -> FastAPI:
    engine = build_engine(database_url or settings.database_url)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        Base.metadata.create_all(engine)
        yield
        engine.dispose()

    app = FastAPI(title="TalentFlow API", version="0.1.0", lifespan=lifespan)
    app.state.session_factory = session_factory

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
    def create_tenant(payload: CreateTenantRequest, session: SessionDep) -> TenantResponse:
        if session.scalar(select(Tenant).where(Tenant.slug == payload.slug)):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Tenant slug already exists"
            )
        tenant = Tenant(name=payload.name, slug=payload.slug)
        user = session.get(User, payload.admin_id) or User(id=payload.admin_id)
        session.add_all([tenant, user])
        session.flush()
        session.add(Membership(tenant_id=tenant.id, user_id=user.id, role="tenant_admin"))
        session.add(
            AuditEvent(
                tenant_id=tenant.id,
                actor_id=user.id,
                action="tenant.created",
                aggregate_type="tenant",
                aggregate_id=tenant.id,
                correlation_id=str(uuid4()),
                metadata_json={"slug": tenant.slug},
            )
        )
        session.commit()
        return TenantResponse(id=tenant.id, name=tenant.name, slug=tenant.slug)

    @app.post(
        "/v1/requisitions", response_model=RequisitionResponse, status_code=status.HTTP_201_CREATED
    )
    def create_requisition(
        payload: CreateRequisitionRequest,
        session: SessionDep,
        actor: ActorContext = Depends(require("requisition:create")),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
    ) -> RequisitionResponse:
        requisition = Requisition(
            tenant_id=actor.tenant_id,
            title=payload.title,
            department=payload.department,
            created_by=actor.actor_id,
        )
        session.add(requisition)
        session.flush()
        session.add(
            AuditEvent(
                tenant_id=actor.tenant_id,
                actor_id=actor.actor_id,
                action="requisition.created",
                aggregate_type="requisition",
                aggregate_id=requisition.id,
                correlation_id=correlation_id or str(uuid4()),
                metadata_json={"title": requisition.title},
            )
        )
        session.commit()
        return RequisitionResponse(
            id=requisition.id, title=requisition.title, department=requisition.department
        )

    @app.get("/v1/candidate-cases", response_model=CandidateListResponse)
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

    @app.post(
        "/v1/candidate-cases",
        response_model=CandidateCaseResponse,
        status_code=status.HTTP_201_CREATED,
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
                unit_of_work=SqlAlchemyCandidateUnitOfWork(session),
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

    @app.patch(
        "/v1/candidate-cases/{candidate_case_id}/stage", response_model=CandidateCaseResponse
    )
    def transition_candidate_case_stage(
        candidate_case_id: str,
        payload: TransitionCandidateCaseRequest,
        request: Request,
        session: SessionDep,
        actor: ActorContext = Depends(require("candidate:transition")),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
    ) -> CandidateCaseResponse:
        candidate_case = session.scalar(
            select(CandidateCase).where(
                CandidateCase.id == candidate_case_id,
                CandidateCase.tenant_id == actor.tenant_id,
            )
        )
        if candidate_case is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Candidate case not found"
            )
        if candidate_case.version != payload.expected_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Candidate case has changed; refresh and retry",
            )
        try:
            target_stage = transition_to(
                CandidateStage(candidate_case.stage), CandidateStage(payload.target_stage)
            )
        except (InvalidTransitionError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
            ) from error

        prior_stage = candidate_case.stage
        try:
            TransitionCandidateHandler(SqlAlchemyCandidateRepository(session)).handle(
                TransitionCandidateCommand(
                    candidate_id=candidate_case_id,
                    tenant_id=actor.tenant_id,
                    target_stage=target_stage.value,
                    expected_version=payload.expected_version,
                )
            )
        except CandidateNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Candidate case not found"
            ) from error
        except ConcurrencyConflictError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Candidate case has changed; refresh and retry",
            ) from error
        session.refresh(candidate_case)
        session.add(
            AuditEvent(
                tenant_id=actor.tenant_id,
                actor_id=actor.actor_id,
                action="candidate_case.stage_transitioned",
                aggregate_type="candidate_case",
                aggregate_id=candidate_case.id,
                correlation_id=correlation_id
                or request.headers.get("X-Request-Id")
                or str(uuid4()),
                metadata_json={
                    "from_stage": prior_stage,
                    "to_stage": candidate_case.stage,
                    "version": candidate_case.version,
                },
            )
        )
        session.commit()
        return CandidateCaseResponse(
            id=candidate_case.id,
            requisition_id=candidate_case.requisition_id,
            first_name=candidate_case.first_name,
            last_name=candidate_case.last_name,
            email=candidate_case.email,
            stage=candidate_case.stage,
            version=candidate_case.version,
        )

    @app.post(
        "/v1/candidate-cases/{candidate_case_id}/interviews",
        response_model=InterviewResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def schedule_interview(
        candidate_case_id: str,
        payload: CreateInterviewRequest,
        request: Request,
        session: SessionDep,
        actor: ActorContext = Depends(require("interview:manage")),
    ) -> InterviewResponse:
        candidate = session.scalar(
            select(CandidateCase).where(
                CandidateCase.id == candidate_case_id, CandidateCase.tenant_id == actor.tenant_id
            )
        )
        interviewer = session.scalar(
            select(Membership).where(
                Membership.tenant_id == actor.tenant_id,
                Membership.user_id == payload.interviewer_id,
                Membership.role == "interviewer",
            )
        )
        if candidate is None or interviewer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate case or interviewer not found",
            )
        interview = Interview(
            tenant_id=actor.tenant_id,
            candidate_case_id=candidate.id,
            interviewer_id=payload.interviewer_id,
            scheduled_at=payload.scheduled_at,
            created_by=actor.actor_id,
        )
        session.add(interview)
        session.flush()
        session.add(
            AuditEvent(
                tenant_id=actor.tenant_id,
                actor_id=actor.actor_id,
                action="interview.scheduled",
                aggregate_type="interview",
                aggregate_id=interview.id,
                correlation_id=request.headers.get("X-Correlation-Id") or str(uuid4()),
                metadata_json={
                    "candidate_case_id": candidate.id,
                    "interviewer_id": interview.interviewer_id,
                },
            )
        )
        session.commit()
        return InterviewResponse(
            id=interview.id,
            candidate_case_id=interview.candidate_case_id,
            interviewer_id=interview.interviewer_id,
            scheduled_at=interview.scheduled_at,
        )

    @app.post(
        "/v1/interviews/{interview_id}/feedback",
        response_model=FeedbackResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def submit_interview_feedback(
        interview_id: str,
        payload: SubmitFeedbackRequest,
        request: Request,
        session: SessionDep,
        actor: ActorContext = Depends(require("feedback:submit")),
    ) -> FeedbackResponse:
        interview = session.scalar(
            select(Interview).where(
                Interview.id == interview_id, Interview.tenant_id == actor.tenant_id
            )
        )
        feedback = session.scalar(
            select(InterviewFeedback).where(InterviewFeedback.interview_id == interview_id)
        )
        if interview is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
        try:
            assert_feedback_can_be_submitted(
                is_assigned=interview.interviewer_id == actor.actor_id,
                feedback_exists=feedback is not None,
            )
        except (InterviewerNotAssignedError, FeedbackAlreadySubmittedError) as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT
                if isinstance(error, FeedbackAlreadySubmittedError)
                else status.HTTP_403_FORBIDDEN,
                detail=str(error),
            ) from error
        feedback = InterviewFeedback(
            tenant_id=actor.tenant_id,
            interview_id=interview.id,
            interviewer_id=actor.actor_id,
            score=payload.score,
            recommendation=payload.recommendation,
            comments=payload.comments.strip(),
        )
        session.add(feedback)
        session.flush()
        session.add(
            AuditEvent(
                tenant_id=actor.tenant_id,
                actor_id=actor.actor_id,
                action="interview.feedback_submitted",
                aggregate_type="interview",
                aggregate_id=interview.id,
                correlation_id=request.headers.get("X-Correlation-Id") or str(uuid4()),
                metadata_json={"score": feedback.score, "recommendation": feedback.recommendation},
            )
        )
        session.commit()
        return FeedbackResponse(
            id=feedback.id,
            interview_id=feedback.interview_id,
            score=feedback.score,
            recommendation=feedback.recommendation,
            comments=feedback.comments,
        )

    @app.post(
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
        except CandidateNotEligibleForOfferError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        except OfferAlreadyExistsError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        return OfferResponse(
            id=offer.id,
            status=offer.status,
            approval_step=offer.approval_step,
            version=offer.version,
            candidate_stage=CandidateStage.OFFER_PENDING_APPROVAL.value,
        )

    @app.post("/v1/offers/{offer_id}/approvals", response_model=OfferResponse)
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
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Offer has changed; refresh and retry"
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

    @app.get("/v1/audit-events", response_model=list[AuditEventResponse])
    def list_audit_events(
        session: SessionDep,
        actor: ActorContext = Depends(require("audit:read")),
    ) -> list[AuditEventResponse]:
        events = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == actor.tenant_id)
            .order_by(AuditEvent.created_at.desc())
        ).all()
        return [
            AuditEventResponse(
                id=event.id,
                action=event.action,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                correlation_id=event.correlation_id,
            )
            for event in events
        ]

    return app


app = create_app()
