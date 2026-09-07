from __future__ import annotations

from typing import Protocol

from app.modules.candidates.domain.candidate_case import CandidateCase
from app.modules.offers.domain.offer import Offer


class OfferRepository(Protocol):
    def get(self, *, offer_id: str, tenant_id: str) -> Offer | None: ...

    def add(
        self, *, offer: Offer, title: str, annual_salary: int, currency: str, created_by: str
    ) -> None: ...

    def update(self, *, offer: Offer, expected_version: int) -> bool: ...

    def record_decision(self, *, offer: Offer, step: int, actor_id: str, decision: str) -> None: ...

    def record_outbox_event(self, *, offer: Offer, actor_id: str, decision: str) -> None: ...


class CandidateWorkflowRepository(Protocol):
    def get(self, *, candidate_id: str, tenant_id: str) -> CandidateCase | None: ...

    def transition(self, *, candidate: CandidateCase, expected_version: int) -> bool: ...


class UnitOfWork(Protocol):
    def commit(self) -> None: ...
