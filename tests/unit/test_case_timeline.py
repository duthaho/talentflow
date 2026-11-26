from datetime import UTC, datetime

import pytest

from app.modules.audit.application.case_timeline import (
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
    redact,
)
from tests.case_timeline_cases import ALLOWLIST_ROWS, BAD_CURSORS, PII


def test_cursor_round_trip_normalizes_to_utc() -> None:
    timestamp = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert decode_cursor(encode_cursor(timestamp, "event-1")) == (timestamp, "event-1")


@pytest.mark.parametrize("cursor", ["!", "e30", "eyJpIjoxfQ", "x" * 257])
def test_invalid_cursor_never_leaks_decoder_errors(cursor: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(cursor)


def test_redact_is_default_deny_and_drops_nested_values() -> None:
    assert (
        redact(
            "candidate_case.created",
            {"stage": {"nested": "value"}, "email": "candidate@example.test"},
        )
        == {}
    )


@pytest.mark.parametrize(
    "cursor", [value for _, value in BAD_CURSORS], ids=[name for name, _ in BAD_CURSORS]
)
def test_spec_bad_cursors_raise_only_invalid_cursor(cursor: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(cursor)


@pytest.mark.parametrize(("action", "expected"), ALLOWLIST_ROWS)
def test_redact_matches_each_spec_allowlist_row(action: str, expected: dict[str, object]) -> None:
    # Include keys valid for other actions too, to catch a global rather than per-action allowlist.
    all_keys = {key: value for _, row in ALLOWLIST_ROWS for key, value in row.items()}
    assert redact(action, {**all_keys, **PII}) == expected


@pytest.mark.parametrize("value", [{"email": "nested@example.test"}, ["nested"], ("nested",)])
def test_redact_drops_containers_under_allowed_keys(value: object) -> None:
    assert redact("candidate_case.created", {"stage": value}) == {}


@pytest.mark.parametrize("value", ["screening", 2, 1.5, True, None])
def test_redact_preserves_allowed_scalar_values(value: object) -> None:
    assert redact("candidate_case.created", {"stage": value}) == {"stage": value}


def test_cursor_length_cap_is_checked_before_base64_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_decode(*_: object) -> None:
        pytest.fail("overlong cursor reached the base64 decoder")

    monkeypatch.setattr(
        "app.modules.audit.application.case_timeline.base64.urlsafe_b64decode", unexpected_decode
    )
    with pytest.raises(InvalidCursorError):
        decode_cursor("x" * 257)
