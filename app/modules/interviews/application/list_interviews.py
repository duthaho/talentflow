from __future__ import annotations

from dataclasses import dataclass

from app.modules.interviews.application.ports import (
    InterviewPage,
    InterviewReadModel,
    decode_cursor,
    encode_cursor,
)


class InterviewListForbiddenError(PermissionError):
    pass


@dataclass(frozen=True)
class ListInterviewsQuery:
    tenant_id: str
    actor_id: str
    can_manage: bool
    interviewer: str | None
    cursor: str | None
    limit: int


class ListInterviewsHandler:
    def __init__(self, interviews: InterviewReadModel):
        self._interviews = interviews

    def handle(self, query: ListInterviewsQuery) -> InterviewPage:
        interviewer_id = self._effective_interviewer(query)
        page = self._interviews.list_page(
            tenant_id=query.tenant_id,
            interviewer_id=interviewer_id,
            cursor=decode_cursor(query.cursor),
            limit=query.limit,
        )
        next_cursor = (
            encode_cursor(page.items[-1].scheduled_at, page.items[-1].id)
            if page.next_cursor is not None and page.items
            else None
        )
        return InterviewPage(items=page.items, next_cursor=next_cursor, total=page.total)

    @staticmethod
    def _effective_interviewer(query: ListInterviewsQuery) -> str | None:
        if query.can_manage:
            return query.actor_id if query.interviewer == "me" else query.interviewer
        if query.interviewer is None or query.interviewer in {"me", query.actor_id}:
            return query.actor_id
        raise InterviewListForbiddenError
