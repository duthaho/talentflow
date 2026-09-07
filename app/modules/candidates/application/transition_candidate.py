from __future__ import annotations

from dataclasses import dataclass

from app.modules.candidates.application.ports import AuditRecorder, CandidateRepository, UnitOfWork
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
    actor_id: str
    correlation_id: str


class TransitionCandidateHandler:
    def __init__(
        self,
        *,
        repository: CandidateRepository,
        audit: AuditRecorder,
        unit_of_work: UnitOfWork,
    ):
        self._repository = repository
        self._audit = audit
        self._unit_of_work = unit_of_work

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
        self._audit.candidate_stage_transitioned(
            candidate=transitioned,
            prior_stage=candidate.stage.value,
            actor_id=command.actor_id,
            correlation_id=command.correlation_id,
        )
        self._unit_of_work.commit()
        return transitioned
