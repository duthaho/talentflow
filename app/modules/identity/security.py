from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select

from app.shared.database import forbidden
from app.shared.models import Membership

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "tenant_admin": frozenset({"requisition:create", "audit:read", "tenant:read"}),
    "recruiter": frozenset({"requisition:create", "tenant:read"}),
    "auditor": frozenset({"audit:read", "tenant:read"}),
    "hiring_manager": frozenset({"tenant:read"}),
    "interviewer": frozenset(),
}


@dataclass(frozen=True)
class ActorContext:
    tenant_id: str
    actor_id: str
    role: str


def require(permission: str):
    def dependency(
        request: Request,
        tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
        actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
    ) -> ActorContext:
        if not tenant_id or not actor_id:
            raise forbidden("X-Tenant-Id and X-Actor-Id headers are required")
        with request.app.state.session_factory() as session:
            membership = session.scalar(
                select(Membership).where(
                    Membership.tenant_id == tenant_id,
                    Membership.user_id == actor_id,
                )
            )
        if membership is None:
            raise forbidden("Actor is not a member of this tenant")
        if permission not in ROLE_PERMISSIONS.get(membership.role, frozenset()):
            raise forbidden("Actor does not have the required permission")
        return ActorContext(tenant_id=tenant_id, actor_id=actor_id, role=membership.role)

    return dependency


ActorDep = Annotated[ActorContext, Depends(require("tenant:read"))]
