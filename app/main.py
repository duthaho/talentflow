from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from sqlalchemy.orm import sessionmaker

from app.api.audit_router import router as audit_router
from app.api.schemas import (
    ApproveOfferRequest,
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
from app.modules.identity.infrastructure.jwt_validator import HttpJwksProvider, JwtValidator
from app.modules.identity.security import ActorContext, require
from app.modules.interviews.application.schedule_interview import (
    InterviewSchedulingTargetNotFoundError,
    ScheduleInterviewCommand,
    ScheduleInterviewHandler,
)
from app.modules.interviews.application.submit_feedback import (
    InterviewNotFoundError,
    SubmitFeedbackCommand,
    SubmitFeedbackHandler,
)
from app.modules.interviews.domain.feedback import (
    FeedbackAlreadySubmittedError,
    InterviewerNotAssignedError,
)
from app.modules.interviews.infrastructure.sqlalchemy_repository import (
    SqlAlchemyInterviewRepository,
)
from app.modules.interviews.infrastructure.sqlalchemy_repository import (
    SqlAlchemyUnitOfWork as SqlAlchemyInterviewUnitOfWork,
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
from app.modules.organization.application.commands import (
    CreateRequisitionCommand,
    CreateTenantCommand,
    OrganizationService,
    TenantSlugAlreadyExistsError,
)
from app.modules.organization.infrastructure.sqlalchemy_repository import (
    SqlAlchemyOrganizationRepository,
)
from app.modules.organization.infrastructure.sqlalchemy_repository import (
    SqlAlchemyUnitOfWork as SqlAlchemyOrganizationUnitOfWork,
)
from app.modules.workflow.domain.candidate_state_machine import (
    CandidateStage,
    InvalidTransitionError,
)
from app.shared.database import SessionDep, build_engine
from app.shared.models import (
    Base,
    CandidateCase,
)
from app.shared.settings import Settings, settings


def create_app(database_url: str | None = None, app_settings: Settings | None = None) -> FastAPI:
    runtime_settings = app_settings or settings
    engine = build_engine(database_url or runtime_settings.database_url)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        Base.metadata.create_all(engine)
        yield
        engine.dispose()

    app = FastAPI(title="TalentFlow API", version="0.1.0", lifespan=lifespan)
    app.state.session_factory = session_factory
    app.state.auth_mode = runtime_settings.auth_mode
    if runtime_settings.auth_mode == "oidc_jwt":
        app.state.token_validator = JwtValidator(
            issuer=runtime_settings.oidc_issuer,
            audience=runtime_settings.oidc_audience,
            algorithms=("RS256",),
            jwks=HttpJwksProvider(
                url=runtime_settings.oidc_jwks_url,
                cache_ttl_seconds=runtime_settings.oidc_jwks_cache_ttl_seconds,
            ),
        )
    app.include_router(audit_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
    def create_tenant(payload: CreateTenantRequest, session: SessionDep) -> TenantResponse:
        try:
            tenant = OrganizationService(
                repository=SqlAlchemyOrganizationRepository(session),
                unit_of_work=SqlAlchemyOrganizationUnitOfWork(session),
            ).create_tenant(
                CreateTenantCommand(name=payload.name, slug=payload.slug, admin_id=payload.admin_id)
            )
        except TenantSlugAlreadyExistsError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
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
        requisition = OrganizationService(
            repository=SqlAlchemyOrganizationRepository(session),
            unit_of_work=SqlAlchemyOrganizationUnitOfWork(session),
        ).create_requisition(
            CreateRequisitionCommand(
                tenant_id=actor.tenant_id,
                title=payload.title,
                department=payload.department,
                actor_id=actor.actor_id,
                correlation_id=correlation_id or str(uuid4()),
            )
        )
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
        try:
            transitioned = TransitionCandidateHandler(
                repository=SqlAlchemyCandidateRepository(session),
                audit=SqlAlchemyAuditRecorder(session),
                unit_of_work=SqlAlchemyCandidateUnitOfWork(session),
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
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Candidate case has changed; refresh and retry",
            ) from error
        except (InvalidTransitionError, ValueError) as error:
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
        try:
            interview = ScheduleInterviewHandler(
                interviews=SqlAlchemyInterviewRepository(session),
                unit_of_work=SqlAlchemyInterviewUnitOfWork(session),
            ).handle(
                ScheduleInterviewCommand(
                    tenant_id=actor.tenant_id,
                    candidate_case_id=candidate_case_id,
                    interviewer_id=payload.interviewer_id,
                    scheduled_at=payload.scheduled_at,
                    actor_id=actor.actor_id,
                    correlation_id=request.headers.get("X-Correlation-Id") or str(uuid4()),
                )
            )
        except InterviewSchedulingTargetNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
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
        try:
            feedback = SubmitFeedbackHandler(
                interviews=SqlAlchemyInterviewRepository(session),
                unit_of_work=SqlAlchemyInterviewUnitOfWork(session),
            ).handle(
                SubmitFeedbackCommand(
                    interview_id=interview_id,
                    tenant_id=actor.tenant_id,
                    actor_id=actor.actor_id,
                    score=payload.score,
                    recommendation=payload.recommendation,
                    comments=payload.comments,
                    correlation_id=request.headers.get("X-Correlation-Id") or str(uuid4()),
                )
            )
        except InterviewNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found"
            ) from error
        except (InterviewerNotAssignedError, FeedbackAlreadySubmittedError) as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT
                if isinstance(error, FeedbackAlreadySubmittedError)
                else status.HTTP_403_FORBIDDEN,
                detail=str(error),
            ) from error
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

    return app


app = create_app()
