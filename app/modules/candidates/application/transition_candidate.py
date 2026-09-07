from __future__ import annotations

from dataclasses import dataclass

from app.modules.candidates.application.ports import CandidateRepository
from app.modules.candidates.domain.candidate_case import CandidateCase
from app.modules.workflow.domain.candidate_state_machine import CandidateStage


class CandidateNotFoundError(LookupError):
    pass


class ConcurrencyConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class TransitionCandidateCommand:
    candidate_id: str
    tenant_id: str
    target_stage: str
    expected_version: int


class TransitionCandidateHandler:
    def __init__(self, repository: CandidateRepository):
        self._repository = repository

    def handle(self, command: TransitionCandidateCommand) -> CandidateCase:
        candidate = self._repository.get(
            candidate_id=command.candidate_id, tenant_id=command.tenant_id
        )
        if candidate is None:
            raise CandidateNotFoundError(command.candidate_id)
        if candidate.version != command.expected_version:
            raise ConcurrencyConflictError(command.candidate_id)
        transitioned = candidate.transition(CandidateStage(command.target_stage))
        if not self._repository.transition(
            candidate=transitioned, expected_version=command.expected_version
        ):
            raise ConcurrencyConflictError(command.candidate_id)
        return transitioned
