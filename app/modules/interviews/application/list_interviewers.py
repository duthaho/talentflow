from __future__ import annotations

from dataclasses import dataclass

from app.modules.interviews.application.ports import InterviewerItem, InterviewReadModel


@dataclass(frozen=True)
class ListInterviewersQuery:
    tenant_id: str
    roles: frozenset[str]


class ListInterviewersHandler:
    def __init__(self, interviews: InterviewReadModel):
        self._interviews = interviews

    def handle(self, query: ListInterviewersQuery) -> list[InterviewerItem]:
        return self._interviews.list_interviewers(tenant_id=query.tenant_id, roles=query.roles)
