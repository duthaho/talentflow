from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.organization.application.ports import RequisitionView, TenantView
from app.shared.models import AuditEvent, Membership, Requisition, Tenant, User


class SqlAlchemyOrganizationRepository:
    def __init__(self, session: Session):
        self._session = session

    def slug_exists(self, *, slug: str) -> bool:
        return self._session.scalar(select(Tenant.id).where(Tenant.slug == slug)) is not None

    def create_tenant(
        self, *, name: str, slug: str, admin_id: str, correlation_id: str
    ) -> TenantView:
        tenant = Tenant(name=name, slug=slug)
        user = self._session.get(User, admin_id) or User(id=admin_id)
        self._session.add_all([tenant, user])
        self._session.flush()
        self._session.add_all(
            [
                Membership(tenant_id=tenant.id, user_id=user.id, role="tenant_admin"),
                AuditEvent(
                    tenant_id=tenant.id,
                    actor_id=user.id,
                    action="tenant.created",
                    aggregate_type="tenant",
                    aggregate_id=tenant.id,
                    correlation_id=correlation_id,
                    metadata_json={"slug": tenant.slug},
                ),
            ]
        )
        return TenantView(tenant.id, tenant.name, tenant.slug)

    def create_requisition(
        self,
        *,
        tenant_id: str,
        title: str,
        department: str,
        actor_id: str,
        correlation_id: str,
    ) -> RequisitionView:
        requisition = Requisition(
            tenant_id=tenant_id, title=title, department=department, created_by=actor_id
        )
        self._session.add(requisition)
        self._session.flush()
        self._session.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_id=actor_id,
                action="requisition.created",
                aggregate_type="requisition",
                aggregate_id=requisition.id,
                correlation_id=correlation_id,
                metadata_json={"title": requisition.title},
            )
        )
        return RequisitionView(requisition.id, requisition.title, requisition.department)


class SqlAlchemyUnitOfWork:
    def __init__(self, session: Session):
        self._session = session

    def commit(self) -> None:
        self._session.commit()
