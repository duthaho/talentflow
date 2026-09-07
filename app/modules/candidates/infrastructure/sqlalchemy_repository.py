from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.modules.candidates.application.ports import CandidateListItem, CandidatePage
from app.modules.candidates.domain.candidate_case import CandidateCase
from app.modules.workflow.domain.candidate_state_machine import CandidateStage
from app.shared.models import AuditEvent, Requisition
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

    def list_page(
        self,
        *,
        tenant_id: str,
        stage: str | None,
        requisition_id: str | None,
        cursor: str | None,
        limit: int,
    ) -> CandidatePage:
        filters = [CandidateCaseRecord.tenant_id == tenant_id]
        if stage:
            filters.append(CandidateCaseRecord.stage == stage)
        if requisition_id:
            filters.append(CandidateCaseRecord.requisition_id == requisition_id)
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
