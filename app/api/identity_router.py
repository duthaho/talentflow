from fastapi import APIRouter, Depends

from app.api.schemas import CurrentActorResponse
from app.modules.identity.security import ROLE_PERMISSIONS, ActorContext, resolve_actor
from app.modules.organization.persistence import Tenant, User
from app.shared.database import SessionDep, forbidden

router = APIRouter()


@router.get("/v1/me", response_model=CurrentActorResponse)
def get_current_actor(
    session: SessionDep, actor: ActorContext = Depends(resolve_actor)
) -> CurrentActorResponse:
    tenant = session.get(Tenant, actor.tenant_id)
    user = session.get(User, actor.actor_id)
    if tenant is None or user is None:
        raise forbidden("Actor is not a member of this tenant")
    return CurrentActorResponse(
        user_id=user.id,
        email=user.email,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        role=actor.role,
        permissions=sorted(ROLE_PERMISSIONS[actor.role]),
    )
