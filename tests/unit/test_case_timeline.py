from datetime import UTC, datetime

import pytest

from app.modules.audit.application.case_timeline import (
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
    redact,
)


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
