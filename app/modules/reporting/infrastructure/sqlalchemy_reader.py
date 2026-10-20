from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.reporting.application.pipeline_report import PipelineReport
from app.shared.models import CandidateCase, Interview, InterviewFeedback, Offer


class SqlAlchemyPipelineReportReader:
    def __init__(self, session: Session):
        self._session = session

    def pipeline_for_tenant(self, *, tenant_id: str) -> PipelineReport:
        candidate_stages = Counter(
            self._session.scalars(
                select(CandidateCase.stage).where(CandidateCase.tenant_id == tenant_id)
            ).all()
        )
        offer_statuses = Counter(
            self._session.scalars(select(Offer.status).where(Offer.tenant_id == tenant_id)).all()
        )
        interview_ids = list(
            self._session.scalars(
                select(Interview.id).where(Interview.tenant_id == tenant_id)
            ).all()
        )
        feedback_total = 0
        if interview_ids:
            feedback_total = len(
                self._session.scalars(
                    select(InterviewFeedback.id).where(
                        InterviewFeedback.tenant_id == tenant_id,
                        InterviewFeedback.interview_id.in_(interview_ids),
                    )
                ).all()
            )
        return PipelineReport(
            candidate_total=sum(candidate_stages.values()),
            candidates_by_stage=dict(sorted(candidate_stages.items())),
            offer_total=sum(offer_statuses.values()),
            offers_by_status=dict(sorted(offer_statuses.items())),
            scheduled_interview_total=len(interview_ids),
            feedback_submitted_total=feedback_total,
        )
