from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select

from app.modules.identity.application.authentication import AuthenticationError, TokenValidator
from app.shared.database import forbidden
from app.shared.models import Membership

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "tenant_admin": frozenset(
        {
            "requisition:create",
            "candidate:create",
            "candidate:transition",
            "interview:manage",
            "audit:read",
            "tenant:read",
        }
    ),
    "recruiter": frozenset(
        {
            "requisition:create",
            "candidate:create",
            "candidate:transition",
            "interview:manage",
            "audit:read",
            "tenant:read",
        }
    ),
    "auditor": frozenset({"audit:read", "tenant:read"}),
    "hiring_manager": frozenset({"tenant:read"}),
    "interviewer": frozenset({"feedback:submit"}),
}


@dataclass(frozen=True)
class ActorContext:
    tenant_id: str
    actor_id: str
    role: str


def require(permission: str):
    def dependency(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
        actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
    ) -> ActorContext:
        if request.app.state.auth_mode == "oidc_jwt":
            if not authorization or not authorization.startswith("Bearer "):
                raise forbidden("Bearer token is required")
            try:
                principal = _validator(request).validate(authorization.removeprefix("Bearer "))
            except AuthenticationError as error:
                raise forbidden(str(error)) from error
            tenant_id, actor_id = principal.tenant_id, principal.subject
        if not tenant_id or not actor_id:
            raise forbidden("X-Tenant-Id and X-Actor-Id headers are required")
        with request.app.state.session_factory() as session:
            membership = session.scalar(
                select(Membership).where(
                    Membership.tenant_id == tenant_id, Membership.user_id == actor_id
                )
            )
        if membership is None:
            raise forbidden("Actor is not a member of this tenant")
        if permission not in ROLE_PERMISSIONS.get(membership.role, frozenset()):
            raise forbidden("Actor does not have the required permission")
        return ActorContext(tenant_id=tenant_id, actor_id=actor_id, role=membership.role)

    return dependency


def _validator(request: Request) -> TokenValidator:
    validator: TokenValidator | None = getattr(request.app.state, "token_validator", None)
    if validator is None:
        raise AuthenticationError("Bearer token validation is not configured")
    return validator


ActorDep = Annotated[ActorContext, Depends(require("tenant:read"))]
