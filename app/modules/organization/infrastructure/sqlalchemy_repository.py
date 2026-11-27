from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.persistence import AuditEvent
from app.modules.organization.application.ports import RequisitionPage, RequisitionView, TenantView
from app.modules.organization.persistence import Membership, Requisition, Tenant, User


def requisition_view(record: Requisition) -> RequisitionView:
    published_at = record.published_at
    if published_at is not None and published_at.tzinfo is None:
        # SQLite drops timezone information; persisted publication times are UTC.
        published_at = published_at.replace(tzinfo=UTC)
    return RequisitionView(
        record.id, record.title, record.department, record.published, published_at
    )


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

    def set_publication(
        self,
        *,
        tenant_id: str,
        requisition_id: str,
        published: bool,
        actor_id: str,
        correlation_id: str,
    ) -> RequisitionView | None:
        record = self._session.scalar(
            select(Requisition)
            .where(Requisition.id == requisition_id, Requisition.tenant_id == tenant_id)
            .with_for_update()
        )
        if record is None:
            return None
        if record.published != published:
            record.published = published
            record.published_at = datetime.now(UTC) if published else None
            self._session.add(
                AuditEvent(
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    action="requisition.published" if published else "requisition.unpublished",
                    aggregate_type="requisition",
                    aggregate_id=record.id,
                    correlation_id=correlation_id,
                    metadata_json={},
                )
            )
        return requisition_view(record)

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
            items=[requisition_view(record) for record in page],
            next_cursor=page[-1].id if len(records) > limit else None,
            total=total,
            tenant_slug=self._session.scalar(select(Tenant.slug).where(Tenant.id == tenant_id))
            or "",
        )


class SqlAlchemyUnitOfWork:
    def __init__(self, session: Session):
        self._session = session

    def commit(self) -> None:
        self._session.commit()


class SqlAlchemyPublicRequisitionRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_public(self, tenant_id: str, *, limit: int):
        from app.modules.organization.application.list_public_requisitions import PublicRequisition

        records = self.session.scalars(
            select(Requisition)
            .where(Requisition.tenant_id == tenant_id, Requisition.published.is_(True))
            .order_by(Requisition.published_at.desc(), Requisition.id)
            .limit(limit)
        ).all()
        return [
            PublicRequisition(record.id, record.title, record.department, record.published_at)
            for record in records
        ]
