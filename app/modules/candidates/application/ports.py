from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.modules.candidates.domain.candidate_case import CandidateCase


@dataclass(frozen=True)
class CandidateListItem:
    id: str
    requisition_id: str
    first_name: str
    last_name: str
    email: str
    stage: str
    version: int


@dataclass(frozen=True)
class CandidatePage:
    items: list[CandidateListItem]
    next_cursor: str | None
    total: int


class CandidateRepository(Protocol):
    def get(self, *, candidate_id: str, tenant_id: str) -> CandidateCase | None: ...

    def transition(self, *, candidate: CandidateCase, expected_version: int) -> bool: ...

    def email_exists(self, *, tenant_id: str, email: str) -> bool: ...

    def add(
        self,
        *,
        candidate: CandidateCase,
        first_name: str,
        last_name: str,
        email: str,
        created_by: str,
    ) -> None: ...

    def list_page(
        self,
        *,
        tenant_id: str,
        stage: str | None,
        requisition_id: str | None,
        cursor: str | None,
        limit: int,
    ) -> CandidatePage: ...


class RequisitionRepository(Protocol):
    def exists(self, *, requisition_id: str, tenant_id: str) -> bool: ...


class AuditRecorder(Protocol):
    def candidate_created(
        self, *, candidate: CandidateCase, actor_id: str, correlation_id: str
    ) -> None: ...


class UnitOfWork(Protocol):
    def commit(self) -> None: ...
