from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select

from app.modules.identity.application.authentication import AuthenticationError, TokenValidator
from app.modules.organization.persistence import Membership
from app.shared.database import forbidden

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "tenant_admin": frozenset(
        {
            "webhook:manage",
            "requisition:create",
            "candidate:create",
            "candidate:transition",
            "candidate:attachment",
            "calendar:manage",
            "interview:manage",
            "audit:read",
            "report:read",
            "tenant:read",
            "retention:manage",
            "retention:purge",
        }
    ),
    "recruiter": frozenset(
        {
            "requisition:create",
            "candidate:create",
            "candidate:transition",
            "candidate:attachment",
            "calendar:manage",
            "interview:manage",
            "audit:read",
            "report:read",
            "tenant:read",
            "retention:manage",
            "retention:purge",
        }
    ),
    "auditor": frozenset({"audit:read", "tenant:read"}),
    "hiring_manager": frozenset({"tenant:read"}),
    "interviewer": frozenset({"calendar:self", "feedback:submit"}),
}


@dataclass(frozen=True)
class ActorContext:
    tenant_id: str
    actor_id: str
    role: str


def resolve_actor(
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
    request.state.actor_id = actor_id
    return ActorContext(tenant_id=tenant_id, actor_id=actor_id, role=membership.role)


def require(permission: str):
    def dependency(actor: Annotated[ActorContext, Depends(resolve_actor)]) -> ActorContext:
        if permission not in ROLE_PERMISSIONS.get(actor.role, frozenset()):
            raise forbidden("Actor does not have the required permission")
        return actor

    return dependency


def permissions_for(role: str) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role, frozenset())


def require_any(*permissions: str):
    def dependency(actor: Annotated[ActorContext, Depends(resolve_actor)]) -> ActorContext:
        if not permissions_for(actor.role).intersection(permissions):
            raise forbidden("Actor does not have the required permission")
        return actor

    return dependency


def _validator(request: Request) -> TokenValidator:
    validator: TokenValidator | None = getattr(request.app.state, "token_validator", None)
    if validator is None:
        raise AuthenticationError("Bearer token validation is not configured")
    return validator


ActorDep = Annotated[ActorContext, Depends(require("tenant:read"))]
