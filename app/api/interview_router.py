from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.schemas import (
    CreateInterviewRequest,
    FeedbackResponse,
    InterviewResponse,
    SubmitFeedbackRequest,
)
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
    SqlAlchemyUnitOfWork,
)
from app.shared.database import SessionDep

router = APIRouter()


@router.post(
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
            unit_of_work=SqlAlchemyUnitOfWork(session),
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


@router.post(
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
            unit_of_work=SqlAlchemyUnitOfWork(session),
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
