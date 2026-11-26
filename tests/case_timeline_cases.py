"""Independent contract examples shared by timeline API and codec tests."""

import base64
import json


def cursor_json(value: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


BAD_CURSORS = [
    ("not-base64", "!!!"),
    ("invalid-padding", "a"),
    ("non-utf8", base64.urlsafe_b64encode(b"\xff").decode()),
    ("invalid-json", base64.urlsafe_b64encode(b"{").decode()),
    ("json-array", cursor_json([])),
    ("json-null", cursor_json(None)),
    ("missing-id", cursor_json({"t": "2026-01-02T03:04:05Z"})),
    ("numeric-id", cursor_json({"t": "2026-01-02T03:04:05Z", "i": 42})),
    ("missing-time", cursor_json({"i": "event"})),
    ("list-time", cursor_json({"t": [], "i": "event"})),
    ("invalid-time", cursor_json({"t": "not-a-date", "i": "event"})),
    ("naive-time", cursor_json({"t": "2026-01-02T03:04:05", "i": "event"})),
    ("over-cap", "x" * 257),
]

# Expected results come from the spec, deliberately not from METADATA_ALLOWLIST.
ALLOWLIST_ROWS = [
    ("candidate_case.created", {"requisition_id": "req-1", "stage": "applied"}),
    (
        "candidate_case.stage_transitioned",
        {"from_stage": "applied", "to_stage": "screening", "version": 2},
    ),
    ("candidate_case.legal_hold_set", {}),
    ("candidate_case.legal_hold_released", {}),
    ("candidate_case.retention_purged", {}),
    (
        "candidate_attachment.uploaded",
        {"document_type": "resume", "content_type": "application/pdf", "size_bytes": 42},
    ),
    ("candidate_attachment.downloaded", {}),
    ("unknown.action", {}),
]
PII = {
    "first_name": "PII-FIRST-SENTINEL",
    "last_name": "PII-LAST-SENTINEL",
    "email": "pii-sentinel@example.test",
    "original_filename": "PII-RESUME-SENTINEL.pdf",
    "sha256": "PII-HASH-SENTINEL",
    "reason": "PII-HOLD-SENTINEL",
    "candidate_case_id": "PII-CASE-SENTINEL",
}
