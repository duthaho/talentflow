from app.modules.candidates.application.ports import CandidateDetail, CandidateRepository
from app.modules.candidates.application.transition_candidate import CandidateNotFoundError


class GetCandidateHandler:
    def __init__(self, repository: CandidateRepository) -> None:
        self._repository = repository

    def handle(self, *, candidate_id: str, tenant_id: str) -> CandidateDetail:
        detail = self._repository.get_detail(candidate_id=candidate_id, tenant_id=tenant_id)
        if detail is None:
            raise CandidateNotFoundError(candidate_id)
        return detail
