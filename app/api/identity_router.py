from fastapi import APIRouter, Depends, Request, Response

from app.api.schemas import CurrentActorResponse, Features, WebhooksFeature
from app.modules.feature_flags.application.flags import ONBOARDING_SAGA, Context, webhooks_state
from app.modules.identity.security import ROLE_PERMISSIONS, ActorContext, resolve_actor
from app.modules.organization.persistence import Tenant, User
from app.shared.database import SessionDep, forbidden

router = APIRouter()


@router.get("/v1/me", response_model=CurrentActorResponse)
def get_current_actor(
    request: Request,
    response: Response,
    session: SessionDep,
    actor: ActorContext = Depends(resolve_actor),
) -> CurrentActorResponse:
    tenant = session.get(Tenant, actor.tenant_id)
    user = session.get(User, actor.actor_id)
    if tenant is None or user is None:
        raise forbidden("Actor is not a member of this tenant")
    response.headers["Cache-Control"] = "private, no-store"
    state = webhooks_state(request.app.state.feature_flags, Context(actor.tenant_id, actor.role))
    return CurrentActorResponse(
        user_id=user.id,
        email=user.email,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        role=actor.role,
        permissions=sorted(ROLE_PERMISSIONS[actor.role]),
        features=Features(
            onboarding=request.app.state.feature_flags.is_enabled(
                ONBOARDING_SAGA, Context(actor.tenant_id, actor.role)
            ),
            webhooks=WebhooksFeature(enabled=state.enabled, delivery_paused=state.delivery_paused),
        ),
    )
