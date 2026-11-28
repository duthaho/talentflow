"""External effects and durable attempt boundary, independent of frameworks."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


@dataclass(frozen=True)
class Claim:
    step_id: str
    owner: str
    saga_id: str
    case_id: str
    step: str
    compensation: bool
    person: dict | None


class Hris(Protocol):
    async def upsert_employee(self, key: str, person: dict) -> str: ...
    async def delete_employee(self, key: str) -> None: ...


class Directory(Protocol):
    async def provision_user(self, case_id: str, saga_id: str, person: dict) -> str: ...
    async def delete_user(self, case_id: str, saga_id: str) -> None: ...


class SagaRepository(Protocol):
    def claim(self, now) -> Claim | bool | None: ...
    def record(self, claim: Claim, now, external_ref=None, error=None) -> bool: ...


@dataclass(frozen=True)
class CandidateSnapshot:
    stage: str
    requisition_id: str
    hire_start_date: date | None
    first_name: str
    last_name: str
    email: str


class Candidates(Protocol):
    def snapshot(self, tenant_id: str, candidate_case_id: str) -> CandidateSnapshot | None: ...


class Clock(Protocol):
    def __call__(self) -> datetime: ...
