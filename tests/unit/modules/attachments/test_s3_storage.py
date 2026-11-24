from app.modules.attachments.infrastructure.s3_storage import S3AttachmentStorage


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
        self.objects[(Bucket, Key)] = Body

    def head_object(self, *, Bucket: str, Key: str) -> None:
        assert (Bucket, Key) in self.objects

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.objects.pop((Bucket, Key), None)

    def generate_presigned_url(
        self, operation_name: str, *, Params: dict[str, str], ExpiresIn: int
    ) -> str:
        assert operation_name == "get_object"
        assert Params == {"Bucket": "attachments", "Key": "attachments/" + "a" * 32}
        assert ExpiresIn == 300
        return "http://seaweedfs:8333/attachments/attachments/" + "a" * 32 + "?signature=example"


def test_s3_storage_saves_deletes_and_generates_bounded_presigned_downloads() -> None:
    client = FakeS3Client()
    storage = S3AttachmentStorage(bucket="attachments", client=client)

    storage.save(storage_key="a" * 32, content=b"resume")
    download = storage.download(storage_key="a" * 32, expires_in_seconds=300)
    storage.delete(storage_key="a" * 32)

    assert client.objects == {}
    assert download.local_path is None
    assert download.presigned_url == (
        "http://seaweedfs:8333/attachments/attachments/" + "a" * 32 + "?signature=example"
    )
