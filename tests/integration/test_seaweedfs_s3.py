import os
import time
from urllib.error import HTTPError
from urllib.request import urlopen
from uuid import uuid4

import pytest

from app.modules.attachments.infrastructure.s3_storage import S3AttachmentStorage


@pytest.mark.skipif(
    not os.getenv("SEAWEEDFS_S3_ENDPOINT"), reason="requires the compose SeaweedFS service"
)
def test_seaweedfs_presigned_url_expires() -> None:
    endpoint = os.environ["SEAWEEDFS_S3_ENDPOINT"]
    storage = S3AttachmentStorage.create(
        endpoint_url=endpoint,
        public_endpoint_url=os.getenv("SEAWEEDFS_S3_PUBLIC_ENDPOINT", endpoint),
        access_key_id=os.environ["SEAWEEDFS_ACCESS_KEY"],
        secret_access_key=os.environ["SEAWEEDFS_SECRET_KEY"],
        bucket="talentflow-attachments",
        region="us-east-1",
    )
    storage_key = uuid4().hex
    storage.save(storage_key=storage_key, content=b"resume")
    try:
        url = storage.download(storage_key=storage_key, expires_in_seconds=5).presigned_url
        assert urlopen(url).read() == b"resume"
        time.sleep(6)
        with pytest.raises(HTTPError) as error:
            urlopen(url)
        assert error.value.code == 403
    finally:
        storage.delete(storage_key=storage_key)
