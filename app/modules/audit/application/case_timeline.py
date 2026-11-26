"""Framework-free primitives for the candidate case audit timeline."""

import base64
import json
from datetime import UTC, datetime

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
