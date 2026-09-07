from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.interviews.application.ports import Feedback
from app.modules.interviews.domain.interview import Interview
from app.shared.models import AuditEvent, CandidateCase, InterviewFeedback, Membership
from app.shared.models import Interview as InterviewRecord


class SqlAlchemyInterviewRepository:
    def __init__(self, session: Session):
        self._session = session

    def candidate_exists(self, *, candidate_id: str, tenant_id: str) -> bool:
        return (
            self._session.scalar(
                select(CandidateCase.id).where(
                    CandidateCase.id == candidate_id, CandidateCase.tenant_id == tenant_id
                )
            )
            is not None
        )

    def interviewer_exists(self, *, interviewer_id: str, tenant_id: str) -> bool:
        return (
            self._session.scalar(
                select(Membership.user_id).where(
                    Membership.tenant_id == tenant_id,
                    Membership.user_id == interviewer_id,
                    Membership.role == "interviewer",
                )
            )
            is not None
        )

    def add(self, *, interview: Interview, created_by: str) -> None:
        self._session.add(
            InterviewRecord(
                id=interview.id,
                tenant_id=interview.tenant_id,
                candidate_case_id=interview.candidate_case_id,
                interviewer_id=interview.interviewer_id,
                scheduled_at=interview.scheduled_at,
                created_by=created_by,
            )
        )

    def get(self, *, interview_id: str, tenant_id: str) -> Interview | None:
        record = self._session.scalar(
            select(InterviewRecord).where(
                InterviewRecord.id == interview_id, InterviewRecord.tenant_id == tenant_id
            )
        )
        return (
            None
            if record is None
            else Interview(
                record.id,
                record.tenant_id,
                record.candidate_case_id,
                record.interviewer_id,
                record.scheduled_at,
            )
        )

    def feedback_exists(self, *, interview_id: str) -> bool:
        return (
            self._session.scalar(
                select(InterviewFeedback.id).where(InterviewFeedback.interview_id == interview_id)
            )
            is not None
        )

    def add_feedback(
        self, *, interview: Interview, score: int, recommendation: str, comments: str
    ) -> Feedback:
        record = InterviewFeedback(
            tenant_id=interview.tenant_id,
            interview_id=interview.id,
            interviewer_id=interview.interviewer_id,
            score=score,
            recommendation=recommendation,
            comments=comments,
        )
        self._session.add(record)
        self._session.flush()
        return Feedback(
            record.id, record.interview_id, record.score, record.recommendation, record.comments
        )

    def record_audit(
        self,
        *,
        action: str,
        aggregate_id: str,
        tenant_id: str,
        actor_id: str,
        correlation_id: str,
        metadata: dict[str, object],
    ) -> None:
        self._session.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_id=actor_id,
                action=action,
                aggregate_type="interview",
                aggregate_id=aggregate_id,
                correlation_id=correlation_id,
                metadata_json=metadata,
            )
        )


class SqlAlchemyUnitOfWork:
    def __init__(self, session: Session):
        self._session = session

    def commit(self) -> None:
        self._session.commit()
