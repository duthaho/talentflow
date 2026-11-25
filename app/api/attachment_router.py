from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse, Response

from app.api.schemas import AttachmentResponse
from app.modules.attachments.application.attachment_service import (
    AttachmentNotFoundError,
    AttachmentService,
    AttachmentTooLargeError,
    CandidateNotFoundError,
    InvalidAttachmentError,
    MalwareScannerUnavailableError,
    MalwareScanRejectedError,
    UploadAttachmentCommand,
)
from app.modules.attachments.infrastructure.filesystem_storage import build_scanner
from app.modules.attachments.infrastructure.sqlalchemy_repository import (
    SqlAlchemyAttachmentRepository,
    SqlAlchemyAuditRecorder,
    SqlAlchemyUnitOfWork,
)
from app.modules.identity.security import ActorContext, require
from app.shared.attachment_storage import build_attachment_storage
from app.shared.database import SessionDep
from app.shared.settings import Settings

router = APIRouter(
    prefix="/v1/candidate-cases/{candidate_case_id}/attachments", tags=["attachments"]
)


def _service(request: Request, session: SessionDep) -> AttachmentService:
    runtime_settings: Settings = request.app.state.runtime_settings
    return AttachmentService(
        repository=SqlAlchemyAttachmentRepository(session),
        storage=build_attachment_storage(runtime_settings),
        scanner=build_scanner(
            mode=runtime_settings.attachment_scan_mode,
            command=runtime_settings.attachment_scan_command,
            clamav_host=runtime_settings.attachment_clamav_host,
            clamav_port=runtime_settings.attachment_clamav_port,
        ),
        audit=SqlAlchemyAuditRecorder(session),
        unit_of_work=SqlAlchemyUnitOfWork(session),
        max_bytes=runtime_settings.attachment_max_bytes,
    )


@router.post("", response_model=AttachmentResponse, status_code=status.HTTP_201_CREATED)
def upload_attachment(
    candidate_case_id: str,
    request: Request,
    file: UploadFile = File(),
    document_type: str = Form(),
    service: AttachmentService = Depends(_service),
    actor: ActorContext = Depends(require("candidate:attachment")),
) -> AttachmentResponse:
    try:
        attachment = service.upload(
            UploadAttachmentCommand(
                tenant_id=actor.tenant_id,
                candidate_case_id=candidate_case_id,
                document_type=document_type,
                filename=file.filename or "",
                content_type=file.content_type or "",
                content=file.file.read(),
                actor_id=actor.actor_id,
                correlation_id=request.headers.get("X-Correlation-Id") or str(uuid4()),
            )
        )
    except CandidateNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Candidate case not found"
        ) from error
    except (InvalidAttachmentError, AttachmentTooLargeError, MalwareScanRejectedError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    except MalwareScannerUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Attachment malware scanner is unavailable",
        ) from error
    return _response(attachment)


@router.get("", response_model=list[AttachmentResponse])
def list_attachments(
    candidate_case_id: str,
    service: AttachmentService = Depends(_service),
    actor: ActorContext = Depends(require("candidate:attachment")),
) -> list[AttachmentResponse]:
    try:
        attachments = service.list(candidate_case_id=candidate_case_id, tenant_id=actor.tenant_id)
    except CandidateNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Candidate case not found"
        ) from error
    return [_response(attachment) for attachment in attachments]


@router.get("/{attachment_id}/download", response_model=None)
def download_attachment(
    candidate_case_id: str,
    attachment_id: str,
    request: Request,
    service: AttachmentService = Depends(_service),
    actor: ActorContext = Depends(require("candidate:attachment")),
) -> Response:
    try:
        attachment, download = service.download(
            attachment_id=attachment_id,
            candidate_case_id=candidate_case_id,
            tenant_id=actor.tenant_id,
            actor_id=actor.actor_id,
            correlation_id=request.headers.get("X-Correlation-Id") or str(uuid4()),
            expires_in_seconds=request.app.state.runtime_settings.attachment_download_ttl_seconds,
        )
    except AttachmentNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found"
        ) from error
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="Attachment content is unavailable"
        ) from error
    if download.presigned_url:
        return RedirectResponse(
            download.presigned_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT
        )
    if download.local_path:
        return FileResponse(
            download.local_path, media_type=attachment.content_type, filename=attachment.filename
        )
    raise RuntimeError("Attachment storage returned no download location")


def _response(attachment: object) -> AttachmentResponse:
    return AttachmentResponse.model_validate(attachment, from_attributes=True)
