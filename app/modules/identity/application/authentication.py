from dataclasses import dataclass
from typing import Protocol


class AuthenticationError(PermissionError):
    pass


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    subject: str
    tenant_id: str


class TokenValidator(Protocol):
    def validate(self, token: str) -> AuthenticatedPrincipal: ...
