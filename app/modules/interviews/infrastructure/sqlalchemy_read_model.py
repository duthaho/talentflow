from datetime import UTC, datetime

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.modules.candidates.persistence import CandidateCase
from app.modules.interviews.application.ports import (
    InterviewerItem,
    InterviewListItem,
    InterviewPage,
)
from app.modules.interviews.persistence import Interview, InterviewFeedback
from app.modules.organization.persistence import Membership, Requisition, User


class SqlAlchemyInterviewReadModel:
    def __init__(self, session: Session):
        self._session = session

    def list_page(
        self,
        *,
        tenant_id: str,
        interviewer_id: str | None,
        cursor: tuple[datetime, str] | None,
        limit: int,
    ) -> InterviewPage:
        filters = [
            Interview.tenant_id == tenant_id,
            CandidateCase.tenant_id == tenant_id,
            Requisition.tenant_id == tenant_id,
        ]
        if interviewer_id is not None:
            filters.append(Interview.interviewer_id == interviewer_id)
        if cursor is not None:
            scheduled_at, interview_id = cursor
            filters.append(
                or_(
                    Interview.scheduled_at > scheduled_at,
                    and_(Interview.scheduled_at == scheduled_at, Interview.id > interview_id),
                )
            )
        submitted = exists(
            select(InterviewFeedback.id).where(InterviewFeedback.interview_id == Interview.id)
        )
        rows = self._session.execute(
            select(
                Interview.id,
                Interview.candidate_case_id,
                CandidateCase.first_name,
                CandidateCase.last_name,
                Requisition.title,
                Interview.interviewer_id,
                User.email,
                Interview.scheduled_at,
                submitted.label("feedback_submitted"),
            )
            .join(CandidateCase, CandidateCase.id == Interview.candidate_case_id)
            .join(Requisition, Requisition.id == CandidateCase.requisition_id)
            .outerjoin(User, User.id == Interview.interviewer_id)
            .where(*filters)
            .order_by(Interview.scheduled_at, Interview.id)
            .limit(limit + 1)
        ).all()
        page_rows = rows[:limit]
        total_filters = filters[:3]
        if interviewer_id is not None:
            total_filters.append(Interview.interviewer_id == interviewer_id)
        total = (
            self._session.scalar(
                select(func.count())
                .select_from(Interview)
                .join(CandidateCase, CandidateCase.id == Interview.candidate_case_id)
                .join(Requisition, Requisition.id == CandidateCase.requisition_id)
                .where(*total_filters)
            )
            or 0
        )
        return InterviewPage(
            items=[
                InterviewListItem(
                    id=row.id,
                    candidate_case_id=row.candidate_case_id,
                    candidate_name=f"{row.first_name} {row.last_name}",
                    requisition_title=row.title,
                    interviewer_id=row.interviewer_id,
                    interviewer_email=row.email,
                    scheduled_at=(
                        row.scheduled_at.replace(tzinfo=UTC)
                        if row.scheduled_at.tzinfo is None
                        else row.scheduled_at
                    ),
                    feedback_submitted=row.feedback_submitted,
                )
                for row in page_rows
            ],
            next_cursor="more" if len(rows) > limit else None,
            total=total,
        )

    def list_interviewers(self, *, tenant_id: str, roles: frozenset[str]) -> list[InterviewerItem]:
        rows = self._session.execute(
            select(Membership.user_id, User.email)
            .join(User, User.id == Membership.user_id)
            .where(Membership.tenant_id == tenant_id, Membership.role.in_(roles))
            .order_by(User.email.is_(None), User.email, Membership.user_id)
        ).all()
        return [InterviewerItem(id=row.user_id, email=row.email) for row in rows]
