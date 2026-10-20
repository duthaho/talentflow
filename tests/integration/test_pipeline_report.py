from fastapi.testclient import TestClient

from app.main import create_app
from tests.integration.test_tenant_rbac import bootstrap_tenant


def test_pipeline_report_is_tenant_scoped_and_exposes_zeroed_operational_counts() -> None:
    with TestClient(create_app("sqlite://")) as client:
        acme = bootstrap_tenant(client, "acme", "admin-1")
        globex = bootstrap_tenant(client, "globex", "admin-2")
        headers = {"X-Tenant-Id": acme["id"], "X-Actor-Id": "admin-1"}
        response = client.get("/v1/reports/pipeline", headers=headers)
        foreign_response = client.get(
            "/v1/reports/pipeline",
            headers={"X-Tenant-Id": globex["id"], "X-Actor-Id": "admin-1"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "candidates": {"total": 0, "by_stage": {}},
        "offers": {"total": 0, "by_status": {}},
        "interviews": {"scheduled_total": 0, "feedback_submitted_total": 0},
    }
    assert foreign_response.status_code == 403
