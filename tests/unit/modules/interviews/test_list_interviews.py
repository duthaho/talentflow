from datetime import UTC, datetime

import pytest

from app.modules.interviews.application.list_interviews import (
    InterviewListForbiddenError,
    ListInterviewsHandler,
    ListInterviewsQuery,
)
from app.modules.interviews.application.ports import (
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
)


@pytest.mark.parametrize(
    ("can_manage", "interviewer", "expected"),
    [
        (True, None, None),
        (True, "me", "actor-1"),
        (True, "person-2", "person-2"),
        (False, None, "actor-1"),
        (False, "me", "actor-1"),
        (False, "actor-1", "actor-1"),
    ],
)
def test_effective_interviewer_scope(
    can_manage: bool, interviewer: str | None, expected: str | None
) -> None:
    query = ListInterviewsQuery(
        tenant_id="tenant-1",
        actor_id="actor-1",
        can_manage=can_manage,
        interviewer=interviewer,
        cursor=None,
        limit=25,
    )

    assert ListInterviewsHandler._effective_interviewer(query) == expected


@pytest.mark.parametrize("interviewer", ["", "ME", " me ", "person-2", "unknown"])
def test_non_manager_cannot_widen_interviewer_scope(interviewer: str) -> None:
    query = ListInterviewsQuery(
        tenant_id="tenant-1",
        actor_id="actor-1",
        can_manage=False,
        interviewer=interviewer,
        cursor=None,
        limit=25,
    )

    with pytest.raises(InterviewListForbiddenError):
        ListInterviewsHandler._effective_interviewer(query)


def test_cursor_round_trip_uses_utc() -> None:
    encoded = encode_cursor(datetime(2026, 10, 1, 9, 0, tzinfo=UTC), "interview-1")

    assert decode_cursor(encoded) == (datetime(2026, 10, 1, 9, 0, tzinfo=UTC), "interview-1")


@pytest.mark.parametrize(
    "cursor",
    [
        "!!!",
        "e30",
        "W10",
        "eyJzIjpudWxsLCJpIjoxfQ",
        "eyJzIjoiMjAyNi0xMC0wMVQwOTowMDowMCIsImkiOiJ4In0",
    ],
)
def test_cursor_rejects_invalid_shapes_and_naive_timestamps(cursor: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(cursor)
