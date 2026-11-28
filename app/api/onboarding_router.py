"""Stable onboarding API for the stage-2 panel. Actions are server decisions."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.conditional_requests import (
    CONDITIONAL_RESPONSES,
    ETAG_RESPONSE,
    IfMatch,
    etag,
    parse_if_match,
    precondition_exception,
)
from app.api.idempotency import CommandRoute
from app.modules.feature_flags.application.flags import ONBOARDING_SAGA, Context
from app.modules.identity.security import ActorContext, permissions_for, require, resolve_actor
from app.modules.onboarding.infrastructure.management import command, view
from app.modules.onboarding.infrastructure.models import Saga
from app.shared.concurrency import (
    InvalidVersionPreconditionError,
    VersionPreconditionFailedError,
    VersionPreconditionRequiredError,
)
from app.shared.database import SessionDep


class StepResponse(BaseModel):
    step: Literal["create_employee", "provision_account", "schedule_tasks", "notify"]
    status: Literal[
        "pending", "in_flight", "retry_wait", "succeeded", "failed", "skipped", "not_run"
    ]
    attempts: int
    last_error: str | None = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
    next_attempt_at: datetime | None
    completed_at: datetime | None
    compensation_status: Literal["pending", "in_flight", "retry_wait", "done", "failed"] | None


class TaskResponse(BaseModel):
    key: Literal["laptop", "accounts", "buddy", "orientation"]
    title: str
    due_date: date
    status: Literal["scheduled", "cancelled"]


class Actions(BaseModel):
    can_retry: bool
    can_cancel: bool


class OnboardingSaga(BaseModel):
    id: UUID
    candidate_case_id: UUID
    status: Literal[
        "running",
        "compensating",
        "compensated",
        "completed",
        "completed_with_warnings",
        "cancelled",
        "compensation_failed",
    ]
    attempt: int
    version: int
    start_date: date
    started_at: datetime
    finished_at: datetime | None
    warning: Literal["notify_exhausted", "no_recipients", "candidate_erased"] | None
    steps: list[StepResponse]
    tasks: list[TaskResponse]
    actions: Actions


def onboarding_actor(request: Request) -> ActorContext:
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
    if "onboarding:manage" not in permissions_for(actor.role):
        raise HTTPException(403, "Actor does not have the required permission")
    return actor


def owned_saga(
    saga_id: UUID,
    request: Request,
    session: SessionDep,
    actor: Annotated[ActorContext, Depends(onboarding_actor)],
):
    saga = session.scalar(
        select(Saga)
        .where(Saga.id == str(saga_id), Saga.tenant_id == actor.tenant_id)
        .with_for_update()
    )
    if saga is None:
        raise HTTPException(404, "Onboarding saga not found")
    if not request.app.state.feature_flags.is_enabled(
        ONBOARDING_SAGA, Context(actor.tenant_id, actor.role)
    ):
        raise HTTPException(
            403,
            {
                "problem_type": "feature-disabled",
                "detail": "Onboarding is disabled for this tenant",
                "feature": "onboarding",
            },
        )
    return saga


router = APIRouter(tags=["onboarding"], route_class=CommandRoute)


@router.get(
    "/v1/candidate-cases/{candidate_case_id}/onboarding",
    response_model=OnboardingSaga,
    responses=ETAG_RESPONSE,
    operation_id="getCandidateCaseOnboarding",
)
def read_onboarding(
    candidate_case_id: UUID,
    request: Request,
    response: Response,
    session: SessionDep,
    actor: Annotated[ActorContext, Depends(require("tenant:read"))],
):
    saga = session.scalar(
        select(Saga).where(
            Saga.candidate_case_id == str(candidate_case_id), Saga.tenant_id == actor.tenant_id
        )
    )
    if saga is None:
        raise HTTPException(404, "Onboarding saga not found")
    response.headers["ETag"] = etag(saga.version)
    response.headers["Cache-Control"] = "private, no-store"
    enabled = request.app.state.feature_flags.is_enabled(
        ONBOARDING_SAGA, Context(actor.tenant_id, actor.role)
    )
    return view(
        session,
        saga,
        enabled=enabled,
        may_manage="onboarding:manage" in permissions_for(actor.role),
    )


def act(action, request, response, session, saga, actor):
    try:
        command(
            session,
            saga,
            action,
            parse_if_match(request.headers.getlist("if-match") or None),
            actor.actor_id,
            request.headers.get("x-correlation-id") or str(uuid4()),
        )
    except (
        InvalidVersionPreconditionError,
        VersionPreconditionFailedError,
        VersionPreconditionRequiredError,
    ) as error:
        raise precondition_exception(error) from None
    except ValueError:
        raise HTTPException(
            409, {"detail": "Saga state does not allow this action", "current_status": saga.status}
        ) from None
    result = view(session, saga, enabled=True, may_manage=True)
    # CommandRoute finalizes the idempotency reservation in the same transaction.
    if not getattr(request.state, "idempotency_reservation", None):
        session.commit()
    response.headers["ETag"] = etag(saga.version)
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post(
    "/v1/onboarding-sagas/{saga_id}/retry",
    response_model=OnboardingSaga,
    status_code=202,
    responses=CONDITIONAL_RESPONSES,
    operation_id="retryOnboardingSaga",
)
def retry(
    request: Request,
    response: Response,
    session: SessionDep,
    saga: Annotated[Saga, Depends(owned_saga)],
    actor: Annotated[ActorContext, Depends(onboarding_actor)],
    if_match: IfMatch = None,
):
    return act("retry", request, response, session, saga, actor)


@router.post(
    "/v1/onboarding-sagas/{saga_id}/cancel",
    response_model=OnboardingSaga,
    status_code=202,
    responses=CONDITIONAL_RESPONSES,
    operation_id="cancelOnboardingSaga",
)
def cancel(
    request: Request,
    response: Response,
    session: SessionDep,
    saga: Annotated[Saga, Depends(owned_saga)],
    actor: Annotated[ActorContext, Depends(onboarding_actor)],
    if_match: IfMatch = None,
):
    return act("cancel", request, response, session, saga, actor)
