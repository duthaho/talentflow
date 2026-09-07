from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.modules.interviews.domain.interview import Interview


@dataclass(frozen=True)
class Feedback:
    id: str
    interview_id: str
    score: int
    recommendation: str
    comments: str


class InterviewRepository(Protocol):
    def candidate_exists(self, *, candidate_id: str, tenant_id: str) -> bool: ...
    def interviewer_exists(self, *, interviewer_id: str, tenant_id: str) -> bool: ...
    def add(self, *, interview: Interview, created_by: str) -> None: ...
    def get(self, *, interview_id: str, tenant_id: str) -> Interview | None: ...
    def feedback_exists(self, *, interview_id: str) -> bool: ...
    def add_feedback(
        self, *, interview: Interview, score: int, recommendation: str, comments: str
    ) -> Feedback: ...
    def record_audit(
        self,
        *,
        action: str,
        aggregate_id: str,
        tenant_id: str,
        actor_id: str,
        correlation_id: str,
        metadata: dict[str, object],
    ) -> None: ...


class UnitOfWork(Protocol):
    def commit(self) -> None: ...
