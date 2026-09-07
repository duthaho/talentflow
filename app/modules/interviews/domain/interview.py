from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4


@dataclass(frozen=True)
class Interview:
    id: str
    tenant_id: str
    candidate_case_id: str
    interviewer_id: str
    scheduled_at: datetime

    @classmethod
    def schedule(
        cls, *, tenant_id: str, candidate_case_id: str, interviewer_id: str, scheduled_at: datetime
    ) -> Interview:
        return cls(str(uuid4()), tenant_id, candidate_case_id, interviewer_id, scheduled_at)
