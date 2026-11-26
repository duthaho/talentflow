from app.modules.organization.application.ports import (
    OrganizationRepository,
    RequisitionView,
    UnitOfWork,
)


class RequisitionNotFoundError(ValueError):
    pass


class SetRequisitionPublicationHandler:
    def __init__(self, repository: OrganizationRepository, unit_of_work: UnitOfWork):
        self._repository = repository
        self._unit_of_work = unit_of_work

    def handle(
        self,
        *,
        tenant_id: str,
        requisition_id: str,
        published: bool,
        actor_id: str,
        correlation_id: str,
    ) -> RequisitionView:
        result = self._repository.set_publication(
            tenant_id=tenant_id,
            requisition_id=requisition_id,
            published=published,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        if result is None:
            raise RequisitionNotFoundError()
        self._unit_of_work.commit()
        return result
