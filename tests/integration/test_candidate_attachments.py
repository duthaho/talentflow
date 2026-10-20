from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.settings import Settings
from tests.integration.test_tenant_rbac import bootstrap_tenant


def _create_candidate(client: TestClient, headers: dict[str, str]) -> dict[str, str]:
    requisition = client.post(
        "/v1/requisitions",
        headers=headers,
        json={"title": "Platform Engineer", "department": "Engineering"},
    )
    assert requisition.status_code == 201
    candidate = client.post(
        "/v1/candidate-cases",
        headers=headers,
        json={
            "requisition_id": requisition.json()["id"],
            "first_name": "Avery",
            "last_name": "Nguyen",
            "email": "avery@example.com",
        },
    )
    assert candidate.status_code == 201
    return candidate.json()


def test_candidate_attachment_is_validated_tenant_scoped_and_audited() -> None:
    with TemporaryDirectory() as storage_root:
        app = create_app(
            "sqlite://",
            Settings(app_env="test", attachment_storage_root=storage_root),
        )
        with TestClient(app) as client:
            acme = bootstrap_tenant(client, "acme", "admin-1")
            globex = bootstrap_tenant(client, "globex", "admin-2")
            headers = {"X-Tenant-Id": acme["id"], "X-Actor-Id": "admin-1"}
            candidate = _create_candidate(client, headers)

            uploaded = client.post(
                f"/v1/candidate-cases/{candidate['id']}/attachments",
                headers=headers,
                data={"document_type": "resume"},
                files={"file": ("avery-resume.pdf", b"%PDF-1.7\nresume", "application/pdf")},
            )
            listed = client.get(
                f"/v1/candidate-cases/{candidate['id']}/attachments", headers=headers
            )
            downloaded = client.get(
                f"/v1/candidate-cases/{candidate['id']}/attachments/{uploaded.json()['id']}/download",
                headers=headers,
            )
            cross_tenant = client.get(
                f"/v1/candidate-cases/{candidate['id']}/attachments",
                headers={"X-Tenant-Id": globex["id"], "X-Actor-Id": "admin-2"},
            )
            invalid = client.post(
                f"/v1/candidate-cases/{candidate['id']}/attachments",
                headers=headers,
                data={"document_type": "resume"},
                files={"file": ("script.pdf", b"<script>alert(1)</script>", "application/pdf")},
            )
            audit = client.get("/v1/audit-events", headers=headers)
            stored_files = list(Path(storage_root).iterdir())

    assert uploaded.status_code == 201
    attachment = uploaded.json()
    assert attachment["filename"] == "avery-resume.pdf"
    assert attachment["document_type"] == "resume"
    assert attachment["content_type"] == "application/pdf"
    assert attachment["size_bytes"] == len(b"%PDF-1.7\nresume")
    assert "storage_key" not in attachment
    assert listed.status_code == 200
    assert listed.json() == [attachment]
    assert downloaded.status_code == 200
    assert downloaded.content == b"%PDF-1.7\nresume"
    assert downloaded.headers["content-disposition"] == 'attachment; filename="avery-resume.pdf"'
    assert cross_tenant.status_code == 404
    assert invalid.status_code == 422
    assert [event["action"] for event in audit.json()][:2] == [
        "candidate_attachment.downloaded",
        "candidate_attachment.uploaded",
    ]
    assert stored_files
