from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.modules.workflow.domain.candidate_state_machine import CandidateStage, transition_to


@dataclass(frozen=True)
class CandidateCase:
    id: str
    tenant_id: str
    requisition_id: str
    stage: CandidateStage
    version: int

    @classmethod
    def open(cls, *, tenant_id: str, requisition_id: str) -> CandidateCase:
        return cls(
            id=str(uuid4()),
            tenant_id=tenant_id,
            requisition_id=requisition_id,
            stage=CandidateStage.APPLIED,
            version=1,
        )

    def transition(self, target: CandidateStage) -> CandidateCase:
        return CandidateCase(
            id=self.id,
            tenant_id=self.tenant_id,
            requisition_id=self.requisition_id,
            stage=transition_to(self.stage, target),
            version=self.version + 1,
        )
