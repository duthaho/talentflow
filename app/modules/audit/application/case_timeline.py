"""Framework-free primitives for the candidate case audit timeline."""

import base64
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

METADATA_ALLOWLIST: dict[str, frozenset[str]] = {
    "candidate_case.created": frozenset({"requisition_id", "stage"}),
    "candidate_case.stage_transitioned": frozenset({"from_stage", "to_stage", "version"}),
    "candidate_case.legal_hold_set": frozenset(),
    "candidate_case.legal_hold_released": frozenset(),
    "candidate_case.retention_purged": frozenset(),
    "candidate_attachment.uploaded": frozenset({"document_type", "content_type", "size_bytes"}),
    "candidate_attachment.downloaded": frozenset(),
}


class InvalidCursorError(ValueError):
    pass


class CandidateNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class TimelineEvent:
    id: str
    action: str
    aggregate_type: str
    aggregate_id: str
    actor_id: str
    occurred_at: datetime
    metadata: dict[str, object]


@dataclass(frozen=True)
class TimelinePage:
    items: list[TimelineEvent]
    next_cursor: str | None


class CaseTimelineReader(Protocol):
    def case_exists(self, *, tenant_id: str, candidate_case_id: str) -> bool: ...

    def list_for_case(
        self,
        *,
        tenant_id: str,
        candidate_case_id: str,
        after: tuple[datetime, str] | None,
        limit: int,
    ) -> list[TimelineEvent]: ...


class CaseTimelineHandler:
    def __init__(self, reader: CaseTimelineReader) -> None:
        self._reader = reader

    def handle(
        self, *, tenant_id: str, candidate_case_id: str, cursor: str | None, limit: int
    ) -> TimelinePage:
        if not self._reader.case_exists(tenant_id=tenant_id, candidate_case_id=candidate_case_id):
            raise CandidateNotFoundError(candidate_case_id)
        after = decode_cursor(cursor) if cursor else None
        events = self._reader.list_for_case(
            tenant_id=tenant_id, candidate_case_id=candidate_case_id, after=after, limit=limit + 1
        )
        page = events[:limit]
        return TimelinePage(
            items=[replace(event, metadata=redact(event.action, event.metadata)) for event in page],
            next_cursor=encode_cursor(page[-1].occurred_at, page[-1].id)
            if len(events) > limit and page
            else None,
        )


def redact(action: str, metadata: dict[str, object]) -> dict[str, object]:
    allowed = METADATA_ALLOWLIST.get(action, frozenset())
    scalar = (str, int, float, bool, type(None))
    return {
        key: value
        for key, value in metadata.items()
        if key in allowed and isinstance(value, scalar)
    }


def encode_cursor(created_at: datetime, event_id: str) -> str:
    timestamp = (
        created_at.replace(tzinfo=UTC) if created_at.tzinfo is None else created_at.astimezone(UTC)
    )
    raw = json.dumps({"t": timestamp.isoformat(), "i": event_id}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    if len(cursor) > 256:
        raise InvalidCursorError("Invalid cursor")
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        value = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("i"), str)
            or not isinstance(value.get("t"), str)
        ):
            raise ValueError
        timestamp = datetime.fromisoformat(value["t"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError
        return timestamp.astimezone(UTC), value["i"]
    except (UnicodeDecodeError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise InvalidCursorError("Invalid cursor") from error
