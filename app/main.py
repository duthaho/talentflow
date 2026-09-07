from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.schemas import (
    AuditEventResponse,
    CreateRequisitionRequest,
    CreateTenantRequest,
    RequisitionResponse,
    TenantResponse,
)
from app.modules.identity.security import ActorContext, require
from app.shared.database import SessionDep, build_engine
from app.shared.models import AuditEvent, Base, Membership, Requisition, Tenant, User
from app.shared.settings import settings


def create_app(database_url: str | None = None) -> FastAPI:
    engine = build_engine(database_url or settings.database_url)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        Base.metadata.create_all(engine)
        yield
        engine.dispose()

    app = FastAPI(title="TalentFlow API", version="0.1.0", lifespan=lifespan)
    app.state.session_factory = session_factory

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
    def create_tenant(payload: CreateTenantRequest, session: SessionDep) -> TenantResponse:
        if session.scalar(select(Tenant).where(Tenant.slug == payload.slug)):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Tenant slug already exists"
            )
        tenant = Tenant(name=payload.name, slug=payload.slug)
        user = session.get(User, payload.admin_id) or User(id=payload.admin_id)
        session.add_all([tenant, user])
        session.flush()
        session.add(Membership(tenant_id=tenant.id, user_id=user.id, role="tenant_admin"))
        session.add(
            AuditEvent(
                tenant_id=tenant.id,
                actor_id=user.id,
                action="tenant.created",
                aggregate_type="tenant",
                aggregate_id=tenant.id,
                correlation_id=str(uuid4()),
                metadata_json={"slug": tenant.slug},
            )
        )
        session.commit()
        return TenantResponse(id=tenant.id, name=tenant.name, slug=tenant.slug)

    @app.post(
        "/v1/requisitions", response_model=RequisitionResponse, status_code=status.HTTP_201_CREATED
    )
    def create_requisition(
        payload: CreateRequisitionRequest,
        session: SessionDep,
        actor: ActorContext = Depends(require("requisition:create")),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
    ) -> RequisitionResponse:
        requisition = Requisition(
            tenant_id=actor.tenant_id,
            title=payload.title,
            department=payload.department,
            created_by=actor.actor_id,
        )
        session.add(requisition)
        session.flush()
        session.add(
            AuditEvent(
                tenant_id=actor.tenant_id,
                actor_id=actor.actor_id,
                action="requisition.created",
                aggregate_type="requisition",
                aggregate_id=requisition.id,
                correlation_id=correlation_id or str(uuid4()),
                metadata_json={"title": requisition.title},
            )
        )
        session.commit()
        return RequisitionResponse(
            id=requisition.id, title=requisition.title, department=requisition.department
        )

    @app.get("/v1/audit-events", response_model=list[AuditEventResponse])
    def list_audit_events(
        session: SessionDep,
        actor: ActorContext = Depends(require("audit:read")),
    ) -> list[AuditEventResponse]:
        events = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == actor.tenant_id)
            .order_by(AuditEvent.created_at.desc())
        ).all()
        return [
            AuditEventResponse(
                id=event.id,
                action=event.action,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                correlation_id=event.correlation_id,
            )
            for event in events
        ]

    return app


app = create_app()
