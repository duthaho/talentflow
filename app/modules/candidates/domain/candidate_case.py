from __future__ import annotations

from dataclasses import dataclass

from app.modules.workflow.domain.candidate_state_machine import CandidateStage, transition_to


@dataclass(frozen=True)
class CandidateCase:
    id: str
    tenant_id: str
    requisition_id: str
    stage: CandidateStage
    version: int

    def transition(self, target: CandidateStage) -> CandidateCase:
        return CandidateCase(
            id=self.id,
            tenant_id=self.tenant_id,
            requisition_id=self.requisition_id,
            stage=transition_to(self.stage, target),
            version=self.version + 1,
        )
