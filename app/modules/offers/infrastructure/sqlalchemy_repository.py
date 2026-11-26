from __future__ import annotations

from datetime import UTC

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.modules.notifications.persistence import OutboxEvent
from app.modules.offers.application.views import DecisionView, OfferView
from app.modules.offers.domain.offer import Offer
from app.modules.offers.persistence import ApprovalDecision
from app.modules.offers.persistence import Offer as OfferRecord
from app.shared.events import record_event


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

    def has_approved_offer(self, *, candidate_id: str, tenant_id: str) -> bool:
        return (
            self._session.scalar(
                select(OfferRecord.id).where(
                    OfferRecord.candidate_case_id == candidate_id,
                    OfferRecord.tenant_id == tenant_id,
                    OfferRecord.status == "approved",
                )
            )
            is not None
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

        record_event(
            self._session,
            topic="offer.created.v1",
            tenant_id=offer.tenant_id,
            subject=offer.id,
            actor_id=created_by,
            data={
                "offer_id": offer.id,
                "candidate_case_id": offer.candidate_case_id,
                "offer_status": offer.status,
                "approval_step": offer.approval_step,
                "version": offer.version,
            },
        )
        self._link_stage_event(offer)

    def _link_stage_event(self, offer: Offer) -> None:
        for event in self._session.new:
            if (
                isinstance(event, OutboxEvent)
                and event.topic == "candidate_case.stage_changed.v1"
                and event.subject == offer.candidate_case_id
                and event.tenant_id == offer.tenant_id
            ):
                event.payload_json = {**event.payload_json, "offer_id": offer.id}

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

    def record_decision(
        self, *, offer: Offer, step: int, actor_id: str, decision: str, reason: str | None
    ) -> None:
        self._session.add(
            ApprovalDecision(
                offer_id=offer.id,
                tenant_id=offer.tenant_id,
                step=step,
                actor_id=actor_id,
                decision=decision,
                reason=reason,
            )
        )

    def list_offers(
        self,
        *,
        tenant_id: str,
        status: str | None,
        candidate_case_id: str | None,
        approval_steps: frozenset[int] | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[OfferView], str | None, int]:
        predicates = [OfferRecord.tenant_id == tenant_id]
        if status is not None:
            predicates.append(OfferRecord.status == status)
        if candidate_case_id is not None:
            predicates.append(OfferRecord.candidate_case_id == candidate_case_id)
        if approval_steps is not None:
            predicates.append(OfferRecord.approval_step.in_(approval_steps))
        total = self._session.scalar(
            select(func.count()).select_from(OfferRecord).where(*predicates)
        )
        page_predicates = [*predicates]
        if cursor is not None:
            page_predicates.append(OfferRecord.id > cursor)
        records = self._session.scalars(
            select(OfferRecord).where(*page_predicates).order_by(OfferRecord.id).limit(limit + 1)
        ).all()
        next_cursor = records[limit - 1].id if len(records) > limit else None
        return [self._view(record) for record in records[:limit]], next_cursor, total or 0

    def get_view(self, *, offer_id: str, tenant_id: str) -> OfferView | None:
        record = self._session.scalar(
            select(OfferRecord).where(
                OfferRecord.id == offer_id, OfferRecord.tenant_id == tenant_id
            )
        )
        return self._view(record) if record is not None else None

    def list_decisions(self, *, offer_id: str, tenant_id: str) -> list[DecisionView]:
        records = self._session.scalars(
            select(ApprovalDecision)
            .where(ApprovalDecision.offer_id == offer_id, ApprovalDecision.tenant_id == tenant_id)
            .order_by(ApprovalDecision.step)
        ).all()
        return [
            DecisionView(
                record.step,
                record.decision,
                record.actor_id,
                record.decided_at.replace(tzinfo=UTC)
                if record.decided_at is not None and record.decided_at.tzinfo is None
                else record.decided_at,
                record.reason,
            )
            for record in records
        ]

    @staticmethod
    def _view(record: OfferRecord) -> OfferView:
        return OfferView(
            record.id,
            record.tenant_id,
            record.candidate_case_id,
            record.title,
            record.annual_salary,
            record.currency,
            record.status,
            record.approval_step,
            record.version,
        )

    def record_outbox_event(self, *, offer: Offer, actor_id: str, decision: str) -> None:
        current = self.get(offer_id=offer.id, tenant_id=offer.tenant_id)
        record_event(
            self._session,
            topic="offer.approval_recorded.v1",
            tenant_id=offer.tenant_id,
            subject=offer.id,
            actor_id=actor_id,
            data={
                "offer_id": offer.id,
                "decision": decision,
                "actor_id": actor_id,
                "candidate_case_id": offer.candidate_case_id,
                "approval_step": offer.approval_step,
                "offer_status": current.status,
                "version": current.version,
            },
        )
        self._link_stage_event(offer)


class SqlAlchemyUnitOfWork:
    def __init__(self, session: Session):
        self._session = session

    def commit(self) -> None:
        self._session.commit()
