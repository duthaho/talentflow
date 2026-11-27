from app.modules.attachments.application.attachment_service import (
    AttachmentTooLargeError,
    InvalidAttachmentError,
    MalwareScannerUnavailableError,
    MalwareScanRejectedError,
    UploadAttachmentCommand,
)
from app.modules.candidates.application.submit_application import SYSTEM_ACTOR, ApplicationError


class AttachmentIntake:
    def __init__(self, service):
        self.service = service

    def inspect(self, application):
        try:
            return self.service.inspect(
                UploadAttachmentCommand(
                    tenant_id="",
                    candidate_case_id="",
                    document_type="resume",
                    filename=application.filename,
                    content_type=application.content_type,
                    content=application.content,
                    actor_id=SYSTEM_ACTOR,
                    correlation_id=application.correlation_id,
                )
            )
        except (InvalidAttachmentError, AttachmentTooLargeError, MalwareScanRejectedError) as error:
            raise ApplicationError(422, "file was rejected") from error
        except MalwareScannerUnavailableError as error:
            raise ApplicationError(503, "Application scanner temporarily unavailable") from error

    def attach(self, cv, candidate, correlation_id):
        return self.service.attach(
            cv,
            tenant_id=candidate.tenant_id,
            candidate_case_id=candidate.id,
            actor_id=SYSTEM_ACTOR,
            correlation_id=correlation_id,
        ).storage_key

    def discard(self, *, storage_key):
        self.service.discard(storage_key=storage_key)
