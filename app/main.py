from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app.api.schemas import (
    AuditEventResponse,
    CandidateCaseResponse,
    CreateCandidateCaseRequest,
    CreateInterviewRequest,
    CreateRequisitionRequest,
    CreateTenantRequest,
    FeedbackResponse,
    InterviewResponse,
    RequisitionResponse,
    SubmitFeedbackRequest,
    TenantResponse,
    TransitionCandidateCaseRequest,
)
from app.modules.identity.security import ActorContext, require
from app.modules.interviews.domain.feedback import (
    FeedbackAlreadySubmittedError,
    InterviewerNotAssignedError,
    assert_feedback_can_be_submitted,
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
        requisition = session.scalar(
            select(Requisition).where(
                Requisition.id == payload.requisition_id,
                Requisition.tenant_id == actor.tenant_id,
            )
        )
        if requisition is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found"
            )

        email = payload.email.strip().lower()
        if session.scalar(
            select(CandidateCase).where(
                CandidateCase.tenant_id == actor.tenant_id,
                CandidateCase.email == email,
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Candidate email already exists in this tenant",
            )

        candidate_case = CandidateCase(
            tenant_id=actor.tenant_id,
            requisition_id=requisition.id,
            first_name=payload.first_name.strip(),
            last_name=payload.last_name.strip(),
            email=email,
            created_by=actor.actor_id,
        )
        session.add(candidate_case)
        session.flush()
        session.add(
            AuditEvent(
                tenant_id=actor.tenant_id,
                actor_id=actor.actor_id,
                action="candidate_case.created",
                aggregate_type="candidate_case",
                aggregate_id=candidate_case.id,
                correlation_id=correlation_id
                or request.headers.get("X-Request-Id")
                or str(uuid4()),
                metadata_json={"requisition_id": requisition.id, "stage": candidate_case.stage},
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
        update_result = session.execute(
            update(CandidateCase)
            .where(
                CandidateCase.id == candidate_case.id,
                CandidateCase.tenant_id == actor.tenant_id,
                CandidateCase.version == payload.expected_version,
            )
            .values(stage=target_stage.value, version=CandidateCase.version + 1)
        )
        if update_result.rowcount != 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Candidate case has changed; refresh and retry",
            )
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
