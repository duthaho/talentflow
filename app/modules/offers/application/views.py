from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class OfferView:
    id: str
    candidate_case_id: str
    title: str
    annual_salary: int
    currency: str
    status: str
    approval_step: int
    version: int


@dataclass(frozen=True)
class DecisionView:
    step: int
    decision: str
    actor_id: str
    decided_at: datetime | None
    reason: str | None
