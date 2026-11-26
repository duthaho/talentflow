from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TenantView:
    id: str
    name: str
    slug: str


@dataclass(frozen=True)
class RequisitionView:
    id: str
    title: str
    department: str


@dataclass(frozen=True)
class RequisitionPage:
    items: list[RequisitionView]
    next_cursor: str | None
    total: int


class OrganizationRepository(Protocol):
    def slug_exists(self, *, slug: str) -> bool: ...
    def create_tenant(
        self, *, name: str, slug: str, admin_id: str, correlation_id: str
    ) -> TenantView: ...
    def create_requisition(
        self, *, tenant_id: str, title: str, department: str, actor_id: str, correlation_id: str
    ) -> RequisitionView: ...

    def list_requisitions_page(
        self, *, tenant_id: str, cursor: str | None, limit: int
    ) -> RequisitionPage: ...


class UnitOfWork(Protocol):
    def commit(self) -> None: ...
