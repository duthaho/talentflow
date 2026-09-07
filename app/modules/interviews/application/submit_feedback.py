from dataclasses import dataclass

from app.modules.interviews.application.ports import Feedback, InterviewRepository, UnitOfWork
from app.modules.interviews.domain.feedback import assert_feedback_can_be_submitted


class InterviewNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class SubmitFeedbackCommand:
    interview_id: str
    tenant_id: str
    actor_id: str
    score: int
    recommendation: str
    comments: str
    correlation_id: str


class SubmitFeedbackHandler:
    def __init__(self, *, interviews: InterviewRepository, unit_of_work: UnitOfWork):
        self._interviews = interviews
        self._unit_of_work = unit_of_work

    def handle(self, command: SubmitFeedbackCommand) -> Feedback:
        interview = self._interviews.get(
            interview_id=command.interview_id, tenant_id=command.tenant_id
        )
        if interview is None:
            raise InterviewNotFoundError(command.interview_id)
        assert_feedback_can_be_submitted(
            is_assigned=interview.interviewer_id == command.actor_id,
            feedback_exists=self._interviews.feedback_exists(interview_id=interview.id),
        )
        feedback = self._interviews.add_feedback(
            interview=interview,
            score=command.score,
            recommendation=command.recommendation,
            comments=command.comments.strip(),
        )
        self._interviews.record_audit(
            action="interview.feedback_submitted",
            aggregate_id=interview.id,
            tenant_id=command.tenant_id,
            actor_id=command.actor_id,
            correlation_id=command.correlation_id,
            metadata={"score": feedback.score, "recommendation": feedback.recommendation},
        )
        self._unit_of_work.commit()
        return feedback
