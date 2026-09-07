from dataclasses import dataclass
from uuid import uuid4

from app.modules.organization.application.ports import (
    OrganizationRepository,
    RequisitionView,
    TenantView,
    UnitOfWork,
)


class TenantSlugAlreadyExistsError(ValueError):
    pass


@dataclass(frozen=True)
class CreateTenantCommand:
    name: str
    slug: str
    admin_id: str


@dataclass(frozen=True)
class CreateRequisitionCommand:
    tenant_id: str
    title: str
    department: str
    actor_id: str
    correlation_id: str


class OrganizationService:
    def __init__(self, *, repository: OrganizationRepository, unit_of_work: UnitOfWork):
        self._repository = repository
        self._unit_of_work = unit_of_work

    def create_tenant(self, command: CreateTenantCommand) -> TenantView:
        if self._repository.slug_exists(slug=command.slug):
            raise TenantSlugAlreadyExistsError("Tenant slug already exists")
        tenant = self._repository.create_tenant(
            name=command.name,
            slug=command.slug,
            admin_id=command.admin_id,
            correlation_id=str(uuid4()),
        )
        self._unit_of_work.commit()
        return tenant

    def create_requisition(self, command: CreateRequisitionCommand) -> RequisitionView:
        requisition = self._repository.create_requisition(
            tenant_id=command.tenant_id,
            title=command.title,
            department=command.department,
            actor_id=command.actor_id,
            correlation_id=command.correlation_id,
        )
        self._unit_of_work.commit()
        return requisition
