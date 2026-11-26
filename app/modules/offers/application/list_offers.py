from dataclasses import dataclass

from app.modules.offers.application.ports import OfferRepository
from app.modules.offers.application.views import OfferView
from app.modules.offers.domain.approval_policy import ApprovalPolicy


@dataclass(frozen=True)
class ListOffersQuery:
    tenant_id: str
    actor_role: str
    awaiting_me: bool
    candidate_case_id: str | None
    status: str | None
    cursor: str | None
    limit: int


@dataclass(frozen=True)
class OfferPage:
    items: list[OfferView]
    next_cursor: str | None
    total: int


class ListOffersHandler:
    def __init__(self, *, offers: OfferRepository, policy: ApprovalPolicy):
        self._offers = offers
        self._policy = policy

    def handle(self, query: ListOffersQuery) -> OfferPage:
        steps = self._policy.steps_for_role(query.actor_role) if query.awaiting_me else None
        if query.awaiting_me and not steps:
            return OfferPage(items=[], next_cursor=None, total=0)
        items, next_cursor, total = self._offers.list(
            tenant_id=query.tenant_id,
            status="pending_approval" if query.awaiting_me else query.status,
            candidate_case_id=query.candidate_case_id,
            approval_steps=steps,
            cursor=query.cursor,
            limit=query.limit,
        )
        return OfferPage(items=items, next_cursor=next_cursor, total=total)
