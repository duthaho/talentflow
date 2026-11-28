"""Tenant-scoped, execution-time candidate read; anonymized cases are absent."""

from sqlalchemy import select

from app.modules.candidates.persistence import CandidateCase
from app.modules.onboarding.application.ports import CandidateSnapshot


class SqlCandidatesReader:
    def __init__(self, session):
        self.session = session

    def snapshot(self, tenant_id, candidate_case_id):
        record = self.session.scalar(
            select(CandidateCase).where(
                CandidateCase.id == candidate_case_id,
                CandidateCase.tenant_id == tenant_id,
                CandidateCase.anonymized_at.is_(None),
            )
        )
        if record is None:
            return None
        return CandidateSnapshot(
            stage=record.stage,
            requisition_id=record.requisition_id,
            hire_start_date=record.hire_start_date,
            first_name=record.first_name,
            last_name=record.last_name,
            email=record.email,
        )
