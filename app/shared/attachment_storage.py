from app.modules.attachments.application.ports import AttachmentStorage
from app.modules.attachments.infrastructure.filesystem_storage import LocalAttachmentStorage
from app.modules.attachments.infrastructure.s3_storage import S3AttachmentStorage
from app.shared.settings import Settings


def build_attachment_storage(settings: Settings) -> AttachmentStorage:
    if settings.attachment_storage_backend == "filesystem":
        return LocalAttachmentStorage(settings.attachment_storage_root)
    secret = settings.attachment_s3_secret_access_key
    if secret is None:  # guarded by Settings; keeps the adapter total for type checkers.
        raise ValueError("S3 attachment storage requires a secret access key")
    return S3AttachmentStorage.create(
        endpoint_url=settings.attachment_s3_endpoint_url,
        public_endpoint_url=settings.attachment_s3_public_endpoint_url,
        access_key_id=settings.attachment_s3_access_key_id,
        secret_access_key=secret.get_secret_value(),
        bucket=settings.attachment_s3_bucket,
        region=settings.attachment_s3_region,
    )
