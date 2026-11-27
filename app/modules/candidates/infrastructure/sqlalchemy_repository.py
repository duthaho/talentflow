from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.modules.audit.persistence import AuditEvent
from app.modules.candidates.application.ports import (
    CandidateDetail,
    CandidateListItem,
    CandidatePage,
)
from app.modules.candidates.domain.candidate_case import CandidateCase
from app.modules.candidates.persistence import CandidateCase as CandidateCaseRecord
from app.modules.organization.persistence import Requisition
from app.modules.workflow.domain.candidate_state_machine import CandidateStage
from app.shared.events import record_event


class SqlAlchemyCandidateRepository:
    def __init__(self, session: Session):
        self._session = session

    def get_detail(self, *, candidate_id: str, tenant_id: str) -> CandidateDetail | None:
        record = self._session.scalar(
            select(CandidateCaseRecord).where(
                CandidateCaseRecord.id == candidate_id, CandidateCaseRecord.tenant_id == tenant_id
            )
        )
        if record is None:
            return None
        created_at = record.created_at
        return CandidateDetail(
            id=record.id,
            requisition_id=record.requisition_id,
            first_name=record.first_name,
            last_name=record.last_name,
            email=record.email,
            stage=record.stage,
            version=record.version,
            created_at=created_at.replace(tzinfo=UTC) if created_at.tzinfo is None else created_at,
        )

    def get(self, *, candidate_id: str, tenant_id: str) -> CandidateCase | None:
        record = self._session.scalar(
            select(CandidateCaseRecord).where(
                CandidateCaseRecord.id == candidate_id, CandidateCaseRecord.tenant_id == tenant_id
            )
        )
        return self._to_domain(record) if record is not None else None

    def email_exists(self, *, tenant_id: str, email: str) -> bool:
        return (
            self._session.scalar(
                select(CandidateCaseRecord.id).where(
                    CandidateCaseRecord.tenant_id == tenant_id, CandidateCaseRecord.email == email
                )
            )
            is not None
        )

    def add(
        self,
        *,
        candidate: CandidateCase,
        first_name: str,
        last_name: str,
        email: str,
        created_by: str,
    ) -> None:
        self._session.add(
            CandidateCaseRecord(
                id=candidate.id,
                tenant_id=candidate.tenant_id,
                requisition_id=candidate.requisition_id,
                first_name=first_name,
                last_name=last_name,
                email=email,
                stage=candidate.stage.value,
                version=candidate.version,
                created_by=created_by,
            )
        )

        record_event(
            self._session,
            topic="candidate_case.created.v1",
            tenant_id=candidate.tenant_id,
            subject=candidate.id,
            actor_id=created_by,
            data={
                "candidate_case_id": candidate.id,
                "requisition_id": candidate.requisition_id,
                "stage": candidate.stage.value,
                "channel": "recruiter",
                "version": candidate.version,
            },
        )

    def transition(self, *, candidate: CandidateCase, expected_version: int) -> bool:
        prior = self.get(candidate_id=candidate.id, tenant_id=candidate.tenant_id)
        result = self._session.execute(
            update(CandidateCaseRecord)
            .where(
                CandidateCaseRecord.id == candidate.id,
                CandidateCaseRecord.tenant_id == candidate.tenant_id,
                CandidateCaseRecord.version == expected_version,
            )
            .values(
                stage=candidate.stage.value,
                version=candidate.version,
                terminal_at=datetime.now(UTC)
                if candidate.stage.value in {"rejected", "withdrawn"}
                else None,
            )
        )
        if result.rowcount == 1:
            record_event(
                self._session,
                topic="candidate_case.stage_changed.v1",
                tenant_id=candidate.tenant_id,
                subject=candidate.id,
                data={
                    "candidate_case_id": candidate.id,
                    "from_stage": prior.stage.value,
                    "to_stage": candidate.stage.value,
                    "version": candidate.version,
                },
            )
        return result.rowcount == 1

    def list_page(
        self,
        *,
        tenant_id: str,
        stage: str | None,
        requisition_id: str | None,
        cursor: str | None,
        limit: int,
        q: str | None = None,
    ) -> CandidatePage:
        filters = [CandidateCaseRecord.tenant_id == tenant_id]
        if stage:
            filters.append(CandidateCaseRecord.stage == stage)
        if requisition_id:
            filters.append(CandidateCaseRecord.requisition_id == requisition_id)
        if q is not None:
            searchable = (
                CandidateCaseRecord.first_name,
                CandidateCaseRecord.last_name,
                CandidateCaseRecord.first_name + " " + CandidateCaseRecord.last_name,
                CandidateCaseRecord.email,
            )
            filters.append(
                or_(
                    *(
                        func.lower(column).contains(q.lower(), autoescape=True)
                        for column in searchable
                    )
                )
            )
        cursor_filters = [*filters, CandidateCaseRecord.id > cursor] if cursor else filters
        records = self._session.scalars(
            select(CandidateCaseRecord)
            .where(*cursor_filters)
            .order_by(CandidateCaseRecord.id)
            .limit(limit + 1)
        ).all()
        page = records[:limit]
        total = (
            self._session.scalar(
                select(func.count()).select_from(CandidateCaseRecord).where(*filters)
            )
            or 0
        )
        return CandidatePage(
            items=[
                CandidateListItem(
                    id=record.id,
                    requisition_id=record.requisition_id,
                    first_name=record.first_name,
                    last_name=record.last_name,
                    email=record.email,
                    stage=record.stage,
                    version=record.version,
                )
                for record in page
            ],
            next_cursor=page[-1].id if len(records) > limit else None,
            total=total,
        )

    @staticmethod
    def _to_domain(record: CandidateCaseRecord) -> CandidateCase:
        return CandidateCase(
            id=record.id,
            tenant_id=record.tenant_id,
            requisition_id=record.requisition_id,
            stage=CandidateStage(record.stage),
            version=record.version,
        )


class SqlAlchemyRequisitionRepository:
    def __init__(self, session: Session):
        self._session = session

    def exists(self, *, requisition_id: str, tenant_id: str) -> bool:
        return (
            self._session.scalar(
                select(Requisition.id).where(
                    Requisition.id == requisition_id, Requisition.tenant_id == tenant_id
                )
            )
            is not None
        )


class SqlAlchemyAuditRecorder:
    def __init__(self, session: Session):
        self._session = session

    def candidate_created(
        self, *, candidate: CandidateCase, actor_id: str, correlation_id: str
    ) -> None:
        self._session.add(
            AuditEvent(
                tenant_id=candidate.tenant_id,
                actor_id=actor_id,
                action="candidate_case.created",
                aggregate_type="candidate_case",
                aggregate_id=candidate.id,
                correlation_id=correlation_id,
                metadata_json={
                    "requisition_id": candidate.requisition_id,
                    "stage": candidate.stage.value,
                },
            )
        )

    def candidate_stage_transitioned(
        self,
        *,
        candidate: CandidateCase,
        prior_stage: str,
        actor_id: str,
        correlation_id: str,
    ) -> None:
        self._session.add(
            AuditEvent(
                tenant_id=candidate.tenant_id,
                actor_id=actor_id,
                action="candidate_case.stage_transitioned",
                aggregate_type="candidate_case",
                aggregate_id=candidate.id,
                correlation_id=correlation_id,
                metadata_json={
                    "from_stage": prior_stage,
                    "to_stage": candidate.stage.value,
                    "version": candidate.version,
                },
            )
        )


class SqlAlchemyUnitOfWork:
    def __init__(self, session: Session):
        self._session = session

    def commit(self) -> None:
        self._session.commit()
