from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.modules.interviews.domain.interview import Interview


@dataclass(frozen=True)
class Feedback:
    id: str
    interview_id: str
    score: int
    recommendation: str
    comments: str


class InvalidCursorError(ValueError):
    pass


@dataclass(frozen=True)
class InterviewListItem:
    id: str
    candidate_case_id: str
    candidate_name: str
    requisition_title: str
    interviewer_id: str
    interviewer_email: str | None
    scheduled_at: datetime
    feedback_submitted: bool


@dataclass(frozen=True)
class InterviewPage:
    items: list[InterviewListItem]
    next_cursor: str | None
    total: int


@dataclass(frozen=True)
class InterviewerItem:
    id: str
    email: str | None


class InterviewReadModel(Protocol):
    def list_page(
        self,
        *,
        tenant_id: str,
        interviewer_id: str | None,
        cursor: tuple[datetime, str] | None,
        limit: int,
    ) -> InterviewPage: ...

    def list_interviewers(
        self, *, tenant_id: str, roles: frozenset[str]
    ) -> list[InterviewerItem]: ...


def decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if cursor is None:
        return None
    if len(cursor) > 512:
        raise InvalidCursorError
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(decoded)
        if not isinstance(payload, dict) or set(payload) != {"s", "i"}:
            raise ValueError
        scheduled_at, interview_id = payload["s"], payload["i"]
        if not isinstance(scheduled_at, str) or not isinstance(interview_id, str):
            raise ValueError
        parsed = datetime.fromisoformat(scheduled_at)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
    except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise InvalidCursorError from error
    return parsed.astimezone(UTC), interview_id


def encode_cursor(scheduled_at: datetime, interview_id: str) -> str:
    if scheduled_at.tzinfo is None or scheduled_at.utcoffset() is None:
        scheduled_at = scheduled_at.replace(tzinfo=UTC)
    payload = json.dumps(
        {"s": scheduled_at.astimezone(UTC).isoformat(), "i": interview_id},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


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
