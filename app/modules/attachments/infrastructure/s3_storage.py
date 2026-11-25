from typing import Protocol

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.modules.attachments.application.ports import AttachmentDownload


class S3Client(Protocol):
    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None: ...

    def head_object(self, *, Bucket: str, Key: str) -> None: ...

    def delete_object(self, *, Bucket: str, Key: str) -> None: ...

    def generate_presigned_url(
        self, operation_name: str, *, Params: dict[str, str], ExpiresIn: int
    ) -> str: ...


class S3AttachmentStorage:
    """Stores opaque attachment keys in a private S3-compatible bucket."""

    def __init__(self, *, bucket: str, client: S3Client, presigner: S3Client | None = None) -> None:
        self._bucket = bucket
        self._client = client
        self._presigner = presigner or client

    @classmethod
    def create(
        cls,
        *,
        endpoint_url: str,
        public_endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        region: str,
    ) -> "S3AttachmentStorage":
        configuration = Config(signature_version="s3v4", s3={"addressing_style": "path"})
        client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            config=configuration,
        )
        presigner = boto3.client(
            "s3",
            endpoint_url=public_endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            config=configuration,
        )
        return cls(bucket=bucket, client=client, presigner=presigner)

    def save(self, *, storage_key: str, content: bytes) -> None:
        self._client.put_object(
            Bucket=self._bucket, Key=self._object_key(storage_key), Body=content
        )

    def download(self, *, storage_key: str, expires_in_seconds: int) -> AttachmentDownload:
        key = self._object_key(storage_key)
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                raise FileNotFoundError(storage_key) from error
            raise
        return AttachmentDownload(
            presigned_url=self._presigner.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in_seconds,
            )
        )

    def delete(self, *, storage_key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=self._object_key(storage_key))

    @staticmethod
    def _object_key(storage_key: str) -> str:
        if len(storage_key) != 32 or any(
            character not in "0123456789abcdef" for character in storage_key
        ):
            raise ValueError("Invalid attachment storage key")
        return f"attachments/{storage_key}"
