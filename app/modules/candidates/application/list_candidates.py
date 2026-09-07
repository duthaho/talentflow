from __future__ import annotations

from dataclasses import dataclass

from app.modules.candidates.application.ports import CandidatePage, CandidateRepository


@dataclass(frozen=True)
class ListCandidatesQuery:
    tenant_id: str
    stage: str | None
    requisition_id: str | None
    cursor: str | None
    limit: int


class ListCandidatesHandler:
    def __init__(self, candidates: CandidateRepository):
        self._candidates = candidates

    def handle(self, query: ListCandidatesQuery) -> CandidatePage:
        return self._candidates.list_page(
            tenant_id=query.tenant_id,
            stage=query.stage,
            requisition_id=query.requisition_id,
            cursor=query.cursor,
            limit=query.limit,
        )
