from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AuditEventView:
    id: str
    action: str
    aggregate_type: str
    aggregate_id: str
    correlation_id: str


class AuditEventReader(Protocol):
    def list_for_tenant(self, *, tenant_id: str) -> list[AuditEventView]: ...


class ListAuditEventsHandler:
    def __init__(self, reader: AuditEventReader):
        self._reader = reader

    def handle(self, *, tenant_id: str) -> list[AuditEventView]:
        return self._reader.list_for_tenant(tenant_id=tenant_id)
