from dataclasses import dataclass
from datetime import datetime

from app.modules.interviews.application.ports import InterviewRepository, UnitOfWork
from app.modules.interviews.domain.interview import Interview


class InterviewSchedulingTargetNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class ScheduleInterviewCommand:
    tenant_id: str
    candidate_case_id: str
    interviewer_id: str
    scheduled_at: datetime
    actor_id: str
    correlation_id: str


class ScheduleInterviewHandler:
    def __init__(self, *, interviews: InterviewRepository, unit_of_work: UnitOfWork):
        self._interviews = interviews
        self._unit_of_work = unit_of_work

    def handle(self, command: ScheduleInterviewCommand) -> Interview:
        if not self._interviews.candidate_exists(
            candidate_id=command.candidate_case_id, tenant_id=command.tenant_id
        ) or not self._interviews.interviewer_exists(
            interviewer_id=command.interviewer_id, tenant_id=command.tenant_id
        ):
            raise InterviewSchedulingTargetNotFoundError("Candidate case or interviewer not found")
        interview = Interview.schedule(
            tenant_id=command.tenant_id,
            candidate_case_id=command.candidate_case_id,
            interviewer_id=command.interviewer_id,
            scheduled_at=command.scheduled_at,
        )
        self._interviews.add(interview=interview, created_by=command.actor_id)
        self._interviews.record_audit(
            action="interview.scheduled",
            aggregate_id=interview.id,
            tenant_id=command.tenant_id,
            actor_id=command.actor_id,
            correlation_id=command.correlation_id,
            metadata={
                "candidate_case_id": interview.candidate_case_id,
                "interviewer_id": interview.interviewer_id,
            },
        )
        self._unit_of_work.commit()
        return interview
