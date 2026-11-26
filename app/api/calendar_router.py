from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.api.schemas import (
    CalendarSubscriptionResponse,
    CalendarSubscriptionSummary,
    CreateCalendarSubscriptionRequest,
)
from app.modules.calendar.application.calendar_subscription import (
    CalendarScope,
    CalendarSubscriptionForbiddenError,
    CalendarSubscriptionNotFoundError,
    CalendarSubscriptionService,
)
from app.modules.calendar.application.icalendar import render_icalendar
from app.modules.calendar.infrastructure.sqlalchemy_repository import SqlAlchemyCalendarRepository
from app.modules.identity.security import ActorContext, permissions_for, require_any
from app.shared.database import SessionDep
from app.shared.settings import Settings

router = APIRouter(tags=["calendar"])


def _service(session: SessionDep, request: Request) -> CalendarSubscriptionService:
    settings: Settings = request.app.state.runtime_settings
    return CalendarSubscriptionService(
        SqlAlchemyCalendarRepository(session),
        lifetime_days=settings.calendar_subscription_lifetime_days,
    )


@router.post(
    "/v1/calendar-subscriptions",
    description="Idempotency-Key is ignored: this response contains a bearer secret.",
    response_model=CalendarSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_calendar_subscription(
    payload: CreateCalendarSubscriptionRequest,
    request: Request,
    response: Response,
    service: CalendarSubscriptionService = Depends(_service),
    actor: ActorContext = Depends(require_any("calendar:manage", "calendar:self")),
) -> CalendarSubscriptionResponse:
    try:
        subscription, token = service.create(
            tenant_id=actor.tenant_id,
            interviewer_id=payload.interviewer_id,
            actor_id=actor.actor_id,
            scope=_scope(actor),
        )
    except CalendarSubscriptionForbiddenError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Calendar subscription access denied"
        ) from error
    except CalendarSubscriptionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Interviewer not found"
        ) from error
    response.headers["Cache-Control"] = "private, no-store"
    return CalendarSubscriptionResponse(
        id=subscription.id,
        interviewer_id=subscription.interviewer_id,
        feed_url=_feed_url(request, token),
        expires_at=subscription.expires_at,
    )


@router.delete(
    "/v1/calendar-subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT
)
def revoke_calendar_subscription(
    subscription_id: str,
    request: Request,
    service: CalendarSubscriptionService = Depends(_service),
    actor: ActorContext = Depends(require_any("calendar:manage", "calendar:self")),
) -> Response:
    try:
        service.revoke(
            subscription_id=subscription_id,
            tenant_id=actor.tenant_id,
            actor_id=actor.actor_id,
            scope=_scope(actor),
        )
    except CalendarSubscriptionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Calendar subscription not found"
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/v1/calendar-subscriptions", response_model=list[CalendarSubscriptionSummary])
def list_calendar_subscriptions(
    interviewer: Annotated[str, Query(min_length=1, max_length=128)],
    response: Response,
    service: CalendarSubscriptionService = Depends(_service),
    actor: ActorContext = Depends(require_any("calendar:manage", "calendar:self")),
) -> list[CalendarSubscriptionSummary]:
    try:
        subscriptions = service.list_active(
            tenant_id=actor.tenant_id,
            interviewer_id=actor.actor_id if interviewer == "me" else interviewer,
            actor_id=actor.actor_id,
            scope=_scope(actor),
        )
    except CalendarSubscriptionForbiddenError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Calendar subscription access denied"
        ) from error
    response.headers["Cache-Control"] = "private, no-store"
    return [
        CalendarSubscriptionSummary(
            id=subscription.id,
            created_at=subscription.created_at,
            expires_at=subscription.expires_at,
        )
        for subscription in subscriptions
    ]


@router.get("/v1/calendar-feeds/{token}.ics", name="calendar_feed", include_in_schema=False)
def calendar_feed(token: str, request: Request, session: SessionDep) -> Response:
    settings: Settings = request.app.state.runtime_settings
    try:
        _, events = CalendarSubscriptionService(
            SqlAlchemyCalendarRepository(session),
            lifetime_days=settings.calendar_subscription_lifetime_days,
        ).calendar_for_token(token)
    except CalendarSubscriptionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Calendar feed not found"
        ) from error
    return Response(
        content=render_icalendar(
            events=events, duration_minutes=settings.calendar_interview_duration_minutes
        ),
        media_type="text/calendar",
        headers={"Cache-Control": "private, no-store"},
    )


def _feed_url(request: Request, token: str) -> str:
    settings: Settings = request.app.state.runtime_settings
    base_url = settings.calendar_public_base_url.rstrip("/") or str(request.base_url).rstrip("/")
    return f"{base_url}/v1/calendar-feeds/{token}.ics"


def _scope(actor: ActorContext) -> CalendarScope:
    return (
        CalendarScope.MANAGE
        if "calendar:manage" in permissions_for(actor.role)
        else CalendarScope.SELF
    )
