import pytest

from app.modules.interviews.domain.feedback import (
    FeedbackAlreadySubmittedError,
    InterviewerNotAssignedError,
    assert_feedback_can_be_submitted,
)


def test_assigned_interviewer_can_submit_first_feedback() -> None:
    assert_feedback_can_be_submitted(is_assigned=True, feedback_exists=False)


@pytest.mark.parametrize(
    ("is_assigned", "feedback_exists", "error"),
    [
        (False, False, InterviewerNotAssignedError),
        (True, True, FeedbackAlreadySubmittedError),
    ],
)
def test_feedback_submission_enforces_assignment_and_single_submission(
    is_assigned: bool, feedback_exists: bool, error: type[Exception]
) -> None:
    with pytest.raises(error):
        assert_feedback_can_be_submitted(is_assigned=is_assigned, feedback_exists=feedback_exists)
