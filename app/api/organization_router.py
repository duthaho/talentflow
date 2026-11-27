from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.api.idempotency import CommandRoute
from app.api.schemas import (
    CreateRequisitionRequest,
    CreateTenantRequest,
    RequisitionListResponse,
    RequisitionResponse,
    SetRequisitionPublicationRequest,
    TenantResponse,
)
from app.modules.identity.security import ActorContext, require
from app.modules.organization.application.commands import (
    CreateRequisitionCommand,
    CreateTenantCommand,
    InvalidTenantAdminError,
    OrganizationService,
    TenantSlugAlreadyExistsError,
)
from app.modules.organization.application.list_requisitions import (
    ListRequisitionsHandler,
    ListRequisitionsQuery,
)
from app.modules.organization.application.set_requisition_publication import (
    RequisitionNotFoundError,
    SetRequisitionPublicationHandler,
)
from app.modules.organization.infrastructure.sqlalchemy_repository import (
    SqlAlchemyOrganizationRepository,
    SqlAlchemyUnitOfWork,
)
from app.shared.database import SessionDep

router = APIRouter(route_class=CommandRoute)


@router.post(
    "/v1/tenants",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    description="Bootstrap: Idempotency-Key is ignored (no authenticated tenant/actor).",
)
def create_tenant(payload: CreateTenantRequest, session: SessionDep) -> TenantResponse:
    try:
        tenant = OrganizationService(
            repository=SqlAlchemyOrganizationRepository(session),
            unit_of_work=SqlAlchemyUnitOfWork(session),
        ).create_tenant(
            CreateTenantCommand(name=payload.name, slug=payload.slug, admin_id=payload.admin_id)
        )
    except InvalidTenantAdminError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except TenantSlugAlreadyExistsError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return TenantResponse(id=tenant.id, name=tenant.name, slug=tenant.slug)


@router.get("/v1/requisitions", response_model=RequisitionListResponse)
def list_requisitions(
    session: SessionDep,
    actor: ActorContext = Depends(require("tenant:read")),
    cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> RequisitionListResponse:
    page = ListRequisitionsHandler(SqlAlchemyOrganizationRepository(session)).handle(
        ListRequisitionsQuery(tenant_id=actor.tenant_id, cursor=cursor, limit=limit)
    )
    return RequisitionListResponse(
        tenant_slug=page.tenant_slug,
        items=[RequisitionResponse(**item.__dict__) for item in page.items],
        next_cursor=page.next_cursor,
        total=page.total,
    )


@router.post(
    "/v1/requisitions", response_model=RequisitionResponse, status_code=status.HTTP_201_CREATED
)
def create_requisition(
    payload: CreateRequisitionRequest,
    session: SessionDep,
    actor: ActorContext = Depends(require("requisition:create")),
    correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
) -> RequisitionResponse:
    requisition = OrganizationService(
        repository=SqlAlchemyOrganizationRepository(session),
        unit_of_work=SqlAlchemyUnitOfWork(session),
    ).create_requisition(
        CreateRequisitionCommand(
            tenant_id=actor.tenant_id,
            title=payload.title,
            department=payload.department,
            actor_id=actor.actor_id,
            correlation_id=correlation_id or str(uuid4()),
        )
    )
    return RequisitionResponse(
        id=requisition.id, title=requisition.title, department=requisition.department
    )


@router.patch(
    "/v1/requisitions/{id}/publication",
    response_model=RequisitionResponse,
    openapi_extra={"x-idempotency-key": True},
)
def set_requisition_publication(
    id: str,
    payload: SetRequisitionPublicationRequest,
    session: SessionDep,
    actor: ActorContext = Depends(require("requisition:create")),
    correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
) -> RequisitionResponse:
    try:
        result = SetRequisitionPublicationHandler(
            SqlAlchemyOrganizationRepository(session), SqlAlchemyUnitOfWork(session)
        ).handle(
            tenant_id=actor.tenant_id,
            requisition_id=id,
            published=payload.published,
            actor_id=actor.actor_id,
            correlation_id=correlation_id or str(uuid4()),
        )
    except RequisitionNotFoundError as error:
        raise HTTPException(status_code=404, detail="Requisition not found") from error
    return RequisitionResponse(**result.__dict__)
