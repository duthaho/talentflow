from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.candidates.domain.candidate_case import CandidateCase
from app.modules.workflow.domain.candidate_state_machine import CandidateStage
from app.shared.models import CandidateCase as CandidateCaseRecord


class SqlAlchemyCandidateRepository:
    def __init__(self, session: Session):
        self._session = session

    def get(self, *, candidate_id: str, tenant_id: str) -> CandidateCase | None:
        record = self._session.scalar(
            select(CandidateCaseRecord).where(
                CandidateCaseRecord.id == candidate_id, CandidateCaseRecord.tenant_id == tenant_id
            )
        )
        if record is None:
            return None
        return CandidateCase(
            id=record.id,
            tenant_id=record.tenant_id,
            requisition_id=record.requisition_id,
            stage=CandidateStage(record.stage),
            version=record.version,
        )

    def transition(self, *, candidate: CandidateCase, expected_version: int) -> bool:
        result = self._session.execute(
            update(CandidateCaseRecord)
            .where(
                CandidateCaseRecord.id == candidate.id,
                CandidateCaseRecord.tenant_id == candidate.tenant_id,
                CandidateCaseRecord.version == expected_version,
            )
            .values(stage=candidate.stage.value, version=candidate.version)
        )
        return result.rowcount == 1
