from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import uuid4

from app.modules.workflow.domain.candidate_state_machine import CandidateStage, transition_to


@dataclass(frozen=True)
class CandidateCase:
    id: str
    tenant_id: str
    requisition_id: str
    stage: CandidateStage
    version: int
    hire_start_date: date | None = None

    @classmethod
    def open(cls, *, tenant_id: str, requisition_id: str) -> CandidateCase:
        return cls(
            id=str(uuid4()),
            tenant_id=tenant_id,
            requisition_id=requisition_id,
            stage=CandidateStage.APPLIED,
            version=1,
        )

    def transition(self, target: CandidateStage, start_date: date | None = None) -> CandidateCase:
        return CandidateCase(
            id=self.id,
            tenant_id=self.tenant_id,
            requisition_id=self.requisition_id,
            stage=transition_to(self.stage, target),
            version=self.version + 1,
            hire_start_date=start_date if target is CandidateStage.HIRED else self.hire_start_date,
        )
