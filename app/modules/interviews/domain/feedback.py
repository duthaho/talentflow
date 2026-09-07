class InterviewerNotAssignedError(PermissionError):
    pass


class FeedbackAlreadySubmittedError(ValueError):
    pass


def assert_feedback_can_be_submitted(*, is_assigned: bool, feedback_exists: bool) -> None:
    if not is_assigned:
        raise InterviewerNotAssignedError("Only the assigned interviewer can submit feedback")
    if feedback_exists:
        raise FeedbackAlreadySubmittedError("Feedback has already been submitted")
