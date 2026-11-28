"""ADR-008 admin API. Secrets never enter the idempotency reservation store."""

import asyncio
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from app.api.conditional_requests import parse_if_match, precondition_exception
from app.api.idempotency import CommandRoute
from app.modules.feature_flags.application.flags import WEBHOOKS_OUTBOUND, Context
from app.modules.identity.security import ActorContext, permissions_for, resolve_actor
from app.modules.webhooks.application.contracts import EVENT_TYPES, WebhookError
from app.modules.webhooks.infrastructure.cipher import build_cipher
from app.modules.webhooks.infrastructure.egress import EgressError, EgressGuard, parse_allowlist
from app.modules.webhooks.infrastructure.management import Management, delivery_view, page
from app.modules.webhooks.infrastructure.models import Delivery, Endpoint
from app.shared.concurrency import (
    InvalidVersionPreconditionError,
    VersionPreconditionFailedError,
    VersionPreconditionRequiredError,
)
from app.shared.database import SessionDep


def webhook_actor(request: Request) -> ActorContext:
    # Existing routes retain their authentication error behavior. ADR-008 explicitly
    # distinguishes unauthenticated (401) from authenticated but forbidden (403).
    try:
        actor = resolve_actor(
            request,
            request.headers.get("authorization"),
            request.headers.get("x-tenant-id"),
            request.headers.get("x-actor-id"),
        )
    except HTTPException as error:
        if error.detail == "Actor is not a member of this tenant":
            raise
        raise HTTPException(
            401, "Authentication is required", headers={"WWW-Authenticate": "Bearer"}
        ) from None
    if "webhook:manage" not in permissions_for(actor.role):
        raise HTTPException(403, "Actor does not have the required permission")
    return actor


router = APIRouter(tags=["webhooks"], dependencies=[Depends(webhook_actor)])
commands = APIRouter(
    tags=["webhooks"], route_class=CommandRoute, dependencies=[Depends(webhook_actor)]
)


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


EventType = Literal[
    "candidate_case.created.v1",
    "candidate_case.stage_changed.v1",
    "candidate_case.erased.v1",
    "interview.scheduled.v1",
    "offer.created.v1",
]


class CreateEndpoint(Body):
    url: str = Field(max_length=2048)
    event_types: list[EventType] = Field(min_length=1, max_length=20)
    description: str | None = Field(default=None, max_length=200)
    enabled: bool = True

    @field_validator("event_types")
    @classmethod
    def valid_types(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Event types must be distinct")
        return values

    @field_validator("description")
    @classmethod
    def valid_description(cls, value):
        if value is not None and any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value):
            raise ValueError("Description cannot contain control characters")
        return value


class UpdateEndpoint(Body):
    url: str | None = Field(default=None, max_length=2048)
    event_types: list[EventType] | None = Field(default=None, min_length=1, max_length=20)
    description: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None

    @model_validator(mode="after")
    def valid_update(self):
        if not self.model_fields_set:
            raise ValueError("Supply at least one field")
        for name in ("url", "event_types", "enabled"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        if self.event_types is not None:
            CreateEndpoint.valid_types(self.event_types)
        CreateEndpoint.valid_description(self.description)
        return self


class RotateSecret(Body):
    grace_period_seconds: int = Field(default=86400, ge=0, le=604800)


def require_webhooks(request: Request, actor: Annotated[ActorContext, Depends(webhook_actor)]):
    if not request.app.state.feature_flags.is_enabled(
        WEBHOOKS_OUTBOUND, Context(actor.tenant_id, actor.role)
    ):
        raise HTTPException(
            403,
            {
                "problem_type": "feature-disabled",
                "feature": "webhooks",
                "detail": "Webhooks are not enabled for this organization. Existing endpoints can still be viewed, disabled, rotated or deleted.",
            },
            headers={"Cache-Control": "private, no-store"},
        )


def require_webhook_patch(
    payload: UpdateEndpoint,
    request: Request,
    actor: Annotated[ActorContext, Depends(webhook_actor)],
):
    if payload.model_dump(exclude_unset=True) != {"enabled": False}:
        require_webhooks(request, actor)


def problem(error):
    detail = {"problem_type": error.slug, "detail": str(error)}
    if error.pointer:
        detail["errors"] = [{"pointer": error.pointer, "detail": str(error)}]
    return HTTPException(error.status, detail)


def service(
    request: Request,
    session: SessionDep,
    actor: Annotated[ActorContext, Depends(webhook_actor)],
):
    try:
        yield Management(
            session,
            build_cipher(request.app.state.runtime_settings),
            actor.tenant_id,
            actor.actor_id,
            request.state.correlation_id,
        )
    except WebhookError as error:
        session.rollback()
        raise problem(error) from None
    except (
        InvalidVersionPreconditionError,
        VersionPreconditionFailedError,
        VersionPreconditionRequiredError,
    ) as error:
        session.rollback()
        raise precondition_exception(error) from None


Service = Annotated[Management, Depends(service)]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=512)]
EndpointStatus = Literal["enabled", "disabled"]
DeliveryStatus = Literal["pending", "succeeded", "dead_lettered", "cancelled"]


def conditions(request, *, rotation=False):
    tokens = parse_if_match(request.headers.getlist("if-match") or None)
    if rotation and tokens == ("*",):
        raise precondition_exception(
            InvalidVersionPreconditionError("Rotation requires a concrete version")
        )
    return tokens


def tag(response, version):
    response.headers["ETag"] = f'"{version}"'
    response.headers["Cache-Control"] = "private, no-store"


def validate_url(request, value):
    settings = request.app.state.runtime_settings
    guard = getattr(request.app.state, "webhook_egress_guard", None) or EgressGuard(
        allow_http=settings.webhook_allow_http,
        allowlist=parse_allowlist(settings.webhook_private_network_allowlist),
    )
    try:
        return asyncio.run(guard.check(value)).url
    except EgressError as error:
        raise problem(
            WebhookError(422, "webhook-url-not-allowed", str(error), pointer="/url")
        ) from None


@router.get("/v1/webhook-event-types", operation_id="listWebhookEventTypes")
def event_types():
    return {
        "items": [{"type": t, "status": v[0], "description": v[1]} for t, v in EVENT_TYPES.items()]
    }


@router.post(
    "/v1/webhook-endpoints",
    status_code=201,
    operation_id="createWebhookEndpoint",
    dependencies=[Depends(require_webhooks)],
)
def create(payload: CreateEndpoint, request: Request, response: Response, manager: Service):
    data = payload.model_dump()
    data["url"] = validate_url(request, data["url"])
    result = manager.create(data)
    response.headers["Location"] = "/v1/webhook-endpoints/" + result["id"]
    tag(response, result["version"])
    return result


@router.get("/v1/webhook-endpoints", operation_id="listWebhookEndpoints")
def endpoints(
    manager: Service, status: EndpointStatus | None = None, cursor: Cursor = None, limit: Limit = 25
):
    query = select(Endpoint).where(
        Endpoint.tenant_id == manager.tenant_id, Endpoint.status != "deleted"
    )
    if status:
        query = query.where(Endpoint.status == status)
    return page(manager.session, query, Endpoint, cursor, limit, manager.endpoint_view)


@router.get("/v1/webhook-endpoints/{endpoint_id}", operation_id="getWebhookEndpoint")
def endpoint(endpoint_id: UUID, response: Response, manager: Service):
    result = manager.endpoint_view(manager.endpoint(str(endpoint_id)))
    tag(response, result["version"])
    return result


@commands.patch(
    "/v1/webhook-endpoints/{endpoint_id}",
    operation_id="updateWebhookEndpoint",
    dependencies=[Depends(require_webhook_patch)],
    openapi_extra={"x-idempotency-key": True},
)
def patch(
    endpoint_id: UUID,
    payload: UpdateEndpoint,
    request: Request,
    response: Response,
    manager: Service,
):
    data = payload.model_dump(exclude_unset=True)
    if "url" in data:
        data["url"] = validate_url(request, data["url"])
    result = manager.patch(str(endpoint_id), data, conditions(request))
    tag(response, result["version"])
    return result


@router.delete(
    "/v1/webhook-endpoints/{endpoint_id}", status_code=204, operation_id="deleteWebhookEndpoint"
)
def delete(endpoint_id: UUID, request: Request, manager: Service):
    manager.delete(str(endpoint_id), conditions(request))
    return Response(status_code=204, headers={"Cache-Control": "private, no-store"})


@router.post(
    "/v1/webhook-endpoints/{endpoint_id}/secret-rotations",
    status_code=201,
    operation_id="rotateWebhookSecret",
)
def rotate(
    endpoint_id: UUID,
    request: Request,
    response: Response,
    manager: Service,
    payload: RotateSecret | None = None,
):
    result = manager.rotate(
        str(endpoint_id),
        (payload or RotateSecret()).grace_period_seconds,
        conditions(request, rotation=True),
    )
    tag(response, result["endpoint"]["version"])
    return result


@router.get("/v1/webhook-endpoints/{endpoint_id}/deliveries", operation_id="listWebhookDeliveries")
def deliveries(
    endpoint_id: UUID,
    manager: Service,
    status: Annotated[list[DeliveryStatus] | None, Query()] = None,
    event_type: str | None = None,
    event_id: UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    cursor: Cursor = None,
    limit: Limit = 25,
):
    manager.endpoint(str(endpoint_id))
    query = select(Delivery).where(
        Delivery.tenant_id == manager.tenant_id, Delivery.endpoint_id == str(endpoint_id)
    )
    if status:
        query = query.where(Delivery.status.in_(status))
    if event_type:
        if event_type not in EVENT_TYPES:
            raise WebhookError(400, "validation-error", "Unknown event type")
        query = query.where(Delivery.event_type == event_type)
    if event_id:
        query = query.where(Delivery.event_id == str(event_id))
    for bound in (created_from, created_to):
        if bound and bound.tzinfo is None:
            raise WebhookError(400, "validation-error", "Time bounds must include a timezone")
    if created_from:
        query = query.where(Delivery.created_at >= created_from)
    if created_to:
        query = query.where(Delivery.created_at < created_to)
    return page(manager.session, query, Delivery, cursor, limit, delivery_view)


@router.get("/v1/webhook-deliveries/{delivery_id}", operation_id="getWebhookDelivery")
def detail(delivery_id: UUID, manager: Service):
    return manager.detail(str(delivery_id))


@commands.post(
    "/v1/webhook-deliveries/{delivery_id}/redeliveries",
    status_code=202,
    operation_id="redeliverWebhook",
    dependencies=[Depends(require_webhooks)],
)
def redeliver(delivery_id: UUID, response: Response, manager: Service):
    result = manager.redeliver(str(delivery_id))
    response.headers["Location"] = "/v1/webhook-deliveries/" + result["id"]
    response.headers["Cache-Control"] = "private, no-store"
    return result
