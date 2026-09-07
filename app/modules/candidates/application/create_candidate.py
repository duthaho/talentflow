from __future__ import annotations

from dataclasses import dataclass

from app.modules.candidates.application.ports import (
    AuditRecorder,
    CandidateRepository,
    RequisitionRepository,
    UnitOfWork,
)
from app.modules.candidates.domain.candidate_case import CandidateCase


class CandidateEmailAlreadyExistsError(ValueError):
    pass


class RequisitionNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class CreateCandidateCommand:
    tenant_id: str
    requisition_id: str
    first_name: str
    last_name: str
    email: str
    actor_id: str
    correlation_id: str


@dataclass(frozen=True)
class CreatedCandidate:
    candidate: CandidateCase
    first_name: str
    last_name: str
    email: str


class CreateCandidateHandler:
    def __init__(
        self,
        *,
        candidates: CandidateRepository,
        requisitions: RequisitionRepository,
        audit: AuditRecorder,
        unit_of_work: UnitOfWork,
    ):
        self._candidates = candidates
        self._requisitions = requisitions
        self._audit = audit
        self._unit_of_work = unit_of_work

    def handle(self, command: CreateCandidateCommand) -> CreatedCandidate:
        if not self._requisitions.exists(
            requisition_id=command.requisition_id, tenant_id=command.tenant_id
        ):
            raise RequisitionNotFoundError(command.requisition_id)
        email = command.email.strip().lower()
        if self._candidates.email_exists(tenant_id=command.tenant_id, email=email):
            raise CandidateEmailAlreadyExistsError("Candidate email already exists in this tenant")
        candidate = CandidateCase.open(
            tenant_id=command.tenant_id, requisition_id=command.requisition_id
        )
        self._candidates.add(
            candidate=candidate,
            first_name=command.first_name.strip(),
            last_name=command.last_name.strip(),
            email=email,
            created_by=command.actor_id,
        )
        self._audit.candidate_created(
            candidate=candidate,
            actor_id=command.actor_id,
            correlation_id=command.correlation_id,
        )
        self._unit_of_work.commit()
        return CreatedCandidate(
            candidate, command.first_name.strip(), command.last_name.strip(), email
        )
