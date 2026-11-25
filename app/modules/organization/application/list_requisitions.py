from __future__ import annotations

from dataclasses import dataclass

from app.modules.organization.application.ports import OrganizationRepository, RequisitionPage


@dataclass(frozen=True)
class ListRequisitionsQuery:
    tenant_id: str
    cursor: str | None
    limit: int


class ListRequisitionsHandler:
    def __init__(self, repository: OrganizationRepository):
        self._repository = repository

    def handle(self, query: ListRequisitionsQuery) -> RequisitionPage:
        return self._repository.list_requisitions_page(
            tenant_id=query.tenant_id,
            cursor=query.cursor,
            limit=query.limit,
        )
