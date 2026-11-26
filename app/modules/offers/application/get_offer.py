from dataclasses import dataclass

from app.modules.offers.application.decide_offer import OfferNotFoundError
from app.modules.offers.application.ports import OfferRepository
from app.modules.offers.application.views import DecisionView, OfferView
from app.modules.offers.domain.approval_policy import ApprovalPolicy


@dataclass(frozen=True)
class GetOfferQuery:
    tenant_id: str
    offer_id: str
    actor_role: str


@dataclass(frozen=True)
class OfferDetailView:
    offer: OfferView
    awaiting_role: str | None
    can_decide: bool
    decisions: list[DecisionView]


class GetOfferHandler:
    def __init__(self, *, offers: OfferRepository, policy: ApprovalPolicy):
        self._offers = offers
        self._policy = policy

    def handle(self, query: GetOfferQuery) -> OfferDetailView:
        offer = self._offers.get(offer_id=query.offer_id, tenant_id=query.tenant_id)
        view = self._offers.get_view(offer_id=query.offer_id, tenant_id=query.tenant_id)
        if offer is None or view is None:
            raise OfferNotFoundError(query.offer_id)
        awaiting_role = (
            self._policy.required_role(offer.approval_step)
            if offer.status == "pending_approval"
            else None
        )
        return OfferDetailView(
            offer=view,
            awaiting_role=awaiting_role,
            can_decide=offer.can_be_decided_by(actor_role=query.actor_role, policy=self._policy),
            decisions=self._offers.list_decisions(offer_id=offer.id, tenant_id=query.tenant_id),
        )
