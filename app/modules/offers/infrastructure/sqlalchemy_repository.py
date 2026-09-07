from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.offers.domain.offer import Offer
from app.shared.models import ApprovalDecision, OutboxEvent
from app.shared.models import Offer as OfferRecord


class SqlAlchemyOfferRepository:
    def __init__(self, session: Session):
        self._session = session

    def get(self, *, offer_id: str, tenant_id: str) -> Offer | None:
        record = self._session.scalar(
            select(OfferRecord).where(
                OfferRecord.id == offer_id, OfferRecord.tenant_id == tenant_id
            )
        )
        if record is None:
            return None
        return Offer(
            id=record.id,
            tenant_id=record.tenant_id,
            candidate_case_id=record.candidate_case_id,
            status=record.status,
            approval_step=record.approval_step,
            version=record.version,
        )

    def add(
        self, *, offer: Offer, title: str, annual_salary: int, currency: str, created_by: str
    ) -> None:
        self._session.add(
            OfferRecord(
                id=offer.id,
                tenant_id=offer.tenant_id,
                candidate_case_id=offer.candidate_case_id,
                title=title,
                annual_salary=annual_salary,
                currency=currency,
                status=offer.status,
                approval_step=offer.approval_step,
                version=offer.version,
                created_by=created_by,
            )
        )

    def update(self, *, offer: Offer, expected_version: int) -> bool:
        result = self._session.execute(
            update(OfferRecord)
            .where(
                OfferRecord.id == offer.id,
                OfferRecord.tenant_id == offer.tenant_id,
                OfferRecord.version == expected_version,
            )
            .values(
                status=offer.status,
                approval_step=offer.approval_step,
                version=offer.version,
            )
        )
        return result.rowcount == 1

    def record_decision(self, *, offer: Offer, step: int, actor_id: str, decision: str) -> None:
        self._session.add(
            ApprovalDecision(
                offer_id=offer.id,
                tenant_id=offer.tenant_id,
                step=step,
                actor_id=actor_id,
                decision=decision,
            )
        )

    def record_outbox_event(self, *, offer: Offer, actor_id: str, decision: str) -> None:
        self._session.add(
            OutboxEvent(
                tenant_id=offer.tenant_id,
                topic="offer.approval_recorded.v1",
                payload_json={
                    "offer_id": offer.id,
                    "decision": decision,
                    "actor_id": actor_id,
                },
            )
        )


class SqlAlchemyUnitOfWork:
    def __init__(self, session: Session):
        self._session = session

    def commit(self) -> None:
        self._session.commit()
