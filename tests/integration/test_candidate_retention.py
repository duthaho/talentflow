from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from sqlalchemy import update

from app.main import create_app
from app.shared.models import CandidateCase
from app.shared.settings import Settings
from tests.integration.test_tenant_rbac import bootstrap_tenant


def _create_rejected_candidate(
    client: TestClient, headers: dict[str, str], email: str
) -> dict[str, object]:
    requisition = client.post(
        "/v1/requisitions",
        headers=headers,
        json={"title": "Platform Engineer", "department": "Engineering"},
    )
    candidate = client.post(
        "/v1/candidate-cases",
        headers=headers,
        json={
            "requisition_id": requisition.json()["id"],
            "first_name": "Avery",
            "last_name": "Nguyen",
            "email": email,
        },
    )
    rejected = client.patch(
        f"/v1/candidate-cases/{candidate.json()['id']}/stage",
        headers=headers,
        json={"target_stage": "rejected", "expected_version": 1},
    )
    assert rejected.status_code == 200
    return candidate.json()


def test_retention_purge_anonymizes_only_due_terminal_candidates_without_legal_hold() -> None:
    app = create_app("sqlite://", Settings(app_env="test"))
    with TestClient(app) as client:
        acme = bootstrap_tenant(client, "acme", "admin-1")
        globex = bootstrap_tenant(client, "globex", "admin-2")
        acme_headers = {"X-Tenant-Id": acme["id"], "X-Actor-Id": "admin-1"}
        globex_headers = {"X-Tenant-Id": globex["id"], "X-Actor-Id": "admin-2"}
        due = _create_rejected_candidate(client, acme_headers, "due@example.com")
        held = _create_rejected_candidate(client, acme_headers, "held@example.com")
        other_tenant = _create_rejected_candidate(client, globex_headers, "other@example.com")

        policy = client.put(
            "/v1/retention-policy", headers=acme_headers, json={"retention_days": 30}
        )
        legal_hold = client.put(
            f"/v1/candidate-cases/{held['id']}/legal-hold",
            headers=acme_headers,
            json={"held": True, "reason": "Active dispute"},
        )
        with app.state.session_factory() as session:
            session.execute(
                update(CandidateCase)
                .where(CandidateCase.id.in_([due["id"], held["id"], other_tenant["id"]]))
                .values(created_at=datetime.now(UTC) - timedelta(days=31))
            )
            session.commit()
        purged = client.post("/v1/retention/purge", headers=acme_headers)
        listed = client.get("/v1/candidate-cases", headers=acme_headers)
        audit = client.get("/v1/audit-events", headers=acme_headers)

    assert policy.status_code == 200
    assert legal_hold.status_code == 204
    assert purged.status_code == 200
    assert purged.json() == {"purged_count": 1}
    due_item = next(item for item in listed.json()["items"] if item["id"] == due["id"])
    held_item = next(item for item in listed.json()["items"] if item["id"] == held["id"])
    assert due_item["first_name"] == "Redacted"
    assert due_item["last_name"] == "Candidate"
    assert due_item["email"] != "due@example.com"
    assert held_item["email"] == "held@example.com"
    assert "candidate_case.retention_purged" in [event["action"] for event in audit.json()]


def test_retention_purge_deletes_private_attachment_metadata_and_content() -> None:
    with TemporaryDirectory() as storage_root:
        app = create_app(
            "sqlite://", Settings(app_env="test", attachment_storage_root=storage_root)
        )
        with TestClient(app) as client:
            tenant = bootstrap_tenant(client, "acme", "admin-1")
            headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "admin-1"}
            candidate = _create_rejected_candidate(client, headers, "delete@example.com")
            upload = client.post(
                f"/v1/candidate-cases/{candidate['id']}/attachments",
                headers=headers,
                data={"document_type": "resume"},
                files={"file": ("resume.pdf", b"%PDF-1.7\nresume", "application/pdf")},
            )
            assert upload.status_code == 201
            assert list(Path(storage_root).iterdir())
            client.put("/v1/retention-policy", headers=headers, json={"retention_days": 1})
            with app.state.session_factory() as session:
                session.execute(
                    update(CandidateCase)
                    .where(CandidateCase.id == candidate["id"])
                    .values(created_at=datetime.now(UTC) - timedelta(days=2))
                )
                session.commit()
            purge = client.post("/v1/retention/purge", headers=headers)
            attachments = client.get(
                f"/v1/candidate-cases/{candidate['id']}/attachments", headers=headers
            )
            remaining_files = list(Path(storage_root).iterdir())

    assert purge.json() == {"purged_count": 1}
    assert attachments.json() == []
    assert remaining_files == []
