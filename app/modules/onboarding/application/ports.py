"""External effects and durable attempt boundary, independent of frameworks."""

from dataclasses import dataclass
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
    def claim(self, now) -> Claim | None: ...
    def record(self, claim: Claim, now, external_ref=None, error=None) -> bool: ...
