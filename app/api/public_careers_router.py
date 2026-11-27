from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.attachment_router import _service
from app.modules.attachments.application.attachment_service import ALLOWED_CONTENT_TYPES
from app.modules.candidates.application.consent import VERSION, render_consent
from app.modules.candidates.application.submit_application import (
    Application,
    ApplicationError,
    SubmitApplicationHandler,
)
from app.modules.candidates.infrastructure.attachment_intake import AttachmentIntake
from app.modules.candidates.infrastructure.public_application import (
    RedisApplicationThrottle,
    SqlAlchemyApplicationRepository,
    consume,
)
from app.modules.organization.application.list_public_requisitions import (
    ListPublicRequisitionsHandler,
)
from app.modules.organization.infrastructure.sqlalchemy_repository import (
    SqlAlchemyPublicRequisitionRepository,
)
from app.shared.database import SessionDep
from app.shared.observability import careers_applications
from app.shared.rate_limit import client_identifier

router = APIRouter(prefix="/v1/public", tags=["public"])


class PublicTenantResponse(BaseModel):
    name: str
    slug: str


class PublicUploadPolicy(BaseModel):
    max_bytes: int
    content_types: list[str]


class PublicRequisition(BaseModel):
    id: str
    title: str
    department: str
    published_at: datetime


class PublicListing(BaseModel):
    tenant: PublicTenantResponse
    upload_policy: PublicUploadPolicy
    requisitions: list[PublicRequisition]


class PublicConsent(BaseModel):
    version: str
    text: str


class Received(BaseModel):
    status: str = "received"


def tenant_or_404(session, slug):
    tenant = SqlAlchemyApplicationRepository(session).tenant(slug)
    if tenant is None:
        raise HTTPException(404, "Tenant not found")
    return tenant


@router.get("/tenants/{slug}/requisitions", response_model=PublicListing)
def listing(slug: str, request: Request, session: SessionDep) -> dict:
    tenant = tenant_or_404(session, slug)
    jobs = ListPublicRequisitionsHandler(SqlAlchemyPublicRequisitionRepository(session)).handle(
        tenant.id
    )
    return {
        "tenant": {"name": tenant.name, "slug": tenant.slug},
        "upload_policy": {
            "max_bytes": request.app.state.runtime_settings.attachment_max_bytes,
            "content_types": sorted(ALLOWED_CONTENT_TYPES),
        },
        "requisitions": [
            {
                "id": job.id,
                "title": job.title,
                "department": job.department,
                "published_at": job.published_at,
            }
            for job in jobs
        ],
    }


@router.get("/tenants/{slug}/consent", response_model=PublicConsent)
def consent(slug: str, session: SessionDep) -> dict[str, str]:
    tenant = tenant_or_404(session, slug)
    return {"version": VERSION, "text": render_consent(tenant.name, tenant.retention_days)}


_FIELDS = ("first_name", "last_name", "email", "consent_version", "consent_accepted", "website")
_MULTIPART = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": [
                        "first_name",
                        "last_name",
                        "email",
                        "consent_version",
                        "consent_accepted",
                        "cv",
                    ],
                    "properties": {
                        **{name: {"type": "string"} for name in _FIELDS},
                        "cv": {"type": "string", "format": "binary"},
                    },
                }
            }
        },
    }
}


@router.post(
    "/tenants/{slug}/requisitions/{requisition_id}/applications",
    status_code=202,
    description="Idempotency-Key is ignored for anonymous multipart intake; deduplication uses tenant/email.",
    response_model=Received,
    openapi_extra=_MULTIPART,
)
async def apply(slug: str, requisition_id: str, request: Request, session: SessionDep) -> Received:
    settings = request.app.state.runtime_settings
    cap = settings.attachment_max_bytes + 65536
    length = request.headers.get("content-length", "")
    if (
        request.headers.get("transfer-encoding") is not None
        or not length.isascii()
        or not length.isdigit()
    ):
        raise HTTPException(411, "An explicit Content-Length is required")
    if len(length) > 20 or int(length) > cap:
        raise HTTPException(413, "Application is too large")
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.cors_origins:
        raise HTTPException(403, "Cross-origin requests are not allowed")
    try:
        await run_in_threadpool(
            consume,
            request.app.state.rate_limiter,
            f"talentflow:careers:ip:{client_identifier(request, settings.trusted_proxy_cidrs())}",
            settings.careers_apply_limit_per_hour,
            3600,
        )
        # Count the actual body too: a forged length cannot bypass the cap on ASGI transports.
        size = 0
        body = bytearray()
        async for chunk in request.stream():
            size += len(chunk)
            if size > cap:
                raise HTTPException(413, "Application is too large")
            body.extend(chunk)
        request._body = bytes(body)
        try:
            async with request.form(max_files=1, max_fields=8, max_part_size=65536) as form:
                if any(len(form.getlist(key)) > 1 for key in form):
                    raise HTTPException(422, "Duplicate application fields")
                fields = {key: value for key in _FIELDS if isinstance(value := form.get(key), str)}
                cv = form.get("cv")
                application = Application(
                    slug,
                    requisition_id,
                    fields,
                    cv.filename or "" if isinstance(cv, UploadFile) else "",
                    cv.content_type or "" if isinstance(cv, UploadFile) else "",
                    await cv.read(settings.attachment_max_bytes + 1)
                    if isinstance(cv, UploadFile)
                    else b"",
                    request.headers.get("x-correlation-id") or str(uuid4()),
                )
        except StarletteHTTPException as error:
            if error.status_code == 400:
                raise HTTPException(422, "Invalid application form") from error
            raise
        session.info["careers_correlation_id"] = application.correlation_id
        outcome = await run_in_threadpool(
            SubmitApplicationHandler(
                SqlAlchemyApplicationRepository(session),
                AttachmentIntake(_service(request, session)),
                RedisApplicationThrottle(
                    request.app.state.rate_limiter, settings.careers_apply_limit_per_email_per_day
                ),
            ).handle,
            application,
        )
        careers_applications.labels(outcome=outcome).inc()
    except ApplicationError as error:
        careers_applications.labels(
            outcome={429: "rate_limited", 503: "unavailable"}.get(error.status, "rejected")
        ).inc()
        raise HTTPException(
            error.status,
            error.detail,
            headers={"Retry-After": str(error.retry_after)} if error.retry_after else None,
        ) from error
    return Received()
