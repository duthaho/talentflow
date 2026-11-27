"""Framework-free errors and the public event catalog from ADR-006."""

EVENT_TYPES = {
    "candidate_case.created.v1": ("active", "Candidate case created"),
    "candidate_case.stage_changed.v1": ("active", "Candidate case changed stage"),
    "candidate_case.erased.v1": ("reserved", "Candidate case erased"),
    "interview.scheduled.v1": ("active", "Interview scheduled"),
    "offer.created.v1": ("active", "Offer created"),
}


class WebhookError(ValueError):
    def __init__(self, status, slug, detail, *, pointer=None):
        self.status = status
        self.slug = slug
        self.pointer = pointer
        super().__init__(detail)
