from __future__ import annotations

from typing import Protocol

from app.modules.candidates.domain.candidate_case import CandidateCase


class CandidateRepository(Protocol):
    def get(self, *, candidate_id: str, tenant_id: str) -> CandidateCase | None: ...

    def transition(self, *, candidate: CandidateCase, expected_version: int) -> bool: ...
