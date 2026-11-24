from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.schemas import (
    CreateRequisitionRequest,
    CreateTenantRequest,
    RequisitionResponse,
    TenantResponse,
)
from app.modules.identity.security import ActorContext, require
from app.modules.organization.application.commands import (
    CreateRequisitionCommand,
    CreateTenantCommand,
    OrganizationService,
    TenantSlugAlreadyExistsError,
)
from app.modules.organization.infrastructure.sqlalchemy_repository import (
    SqlAlchemyOrganizationRepository,
    SqlAlchemyUnitOfWork,
)
from app.shared.database import SessionDep

router = APIRouter()


@router.post("/v1/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
def create_tenant(payload: CreateTenantRequest, session: SessionDep) -> TenantResponse:
    try:
        tenant = OrganizationService(
            repository=SqlAlchemyOrganizationRepository(session),
            unit_of_work=SqlAlchemyUnitOfWork(session),
        ).create_tenant(
            CreateTenantCommand(name=payload.name, slug=payload.slug, admin_id=payload.admin_id)
        )
    except TenantSlugAlreadyExistsError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return TenantResponse(id=tenant.id, name=tenant.name, slug=tenant.slug)


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
