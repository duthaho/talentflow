from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.persistence import AuditEvent
from app.modules.organization.application.ports import RequisitionPage, RequisitionView, TenantView
from app.modules.organization.persistence import Membership, Requisition, Tenant, User


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

    def list_requisitions_page(
        self, *, tenant_id: str, cursor: str | None, limit: int
    ) -> RequisitionPage:
        filters = [Requisition.tenant_id == tenant_id]
        cursor_filters = [*filters, Requisition.id > cursor] if cursor else filters
        records = self._session.scalars(
            select(Requisition).where(*cursor_filters).order_by(Requisition.id).limit(limit + 1)
        ).all()
        page = records[:limit]
        total = (
            self._session.scalar(select(func.count()).select_from(Requisition).where(*filters)) or 0
        )
        return RequisitionPage(
            items=[RequisitionView(record.id, record.title, record.department) for record in page],
            next_cursor=page[-1].id if len(records) > limit else None,
            total=total,
        )


class SqlAlchemyUnitOfWork:
    def __init__(self, session: Session):
        self._session = session

    def commit(self) -> None:
        self._session.commit()
