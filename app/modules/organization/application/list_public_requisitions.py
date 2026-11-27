from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class PublicRequisition:
    id: str
    title: str
    department: str
    published_at: datetime


class PublicRequisitionRepository(Protocol):
    def list_public(self, tenant_id: str, *, limit: int) -> list[PublicRequisition]: ...


class ListPublicRequisitionsHandler:
    def __init__(self, repository: PublicRequisitionRepository):
        self.repository = repository

    def handle(self, tenant_id: str) -> list[PublicRequisition]:
        return self.repository.list_public(tenant_id, limit=100)
