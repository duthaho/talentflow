from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.models import Membership, User


def test_offer_approval_requires_ordered_roles() -> None:
    app = create_app("sqlite://")
    with TestClient(app) as client:
        tenant = client.post(
            "/v1/tenants", json={"name": "Acme HR", "slug": "acme", "admin_id": "admin"}
        ).json()
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "admin"}
        with app.state.session_factory() as session:
            session.add_all(
                [
                    User(id="manager"),
                    Membership(tenant_id=tenant["id"], user_id="manager", role="hiring_manager"),
                ]
            )
            session.commit()
        req = client.post(
            "/v1/requisitions",
            headers=headers,
            json={"title": "Staff Engineer", "department": "Engineering"},
        ).json()
        candidate = client.post(
            "/v1/candidate-cases",
            headers=headers,
            json={
                "requisition_id": req["id"],
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ada@example.com",
            },
        ).json()
        client.patch(
            f"/v1/candidate-cases/{candidate['id']}/stage",
            headers=headers,
            json={"target_stage": "screening", "expected_version": 1},
        )
        client.patch(
            f"/v1/candidate-cases/{candidate['id']}/stage",
            headers=headers,
            json={"target_stage": "interviewing", "expected_version": 2},
        )
        offer = client.post(
            f"/v1/candidate-cases/{candidate['id']}/offers",
            headers=headers,
            json={"title": "Staff Engineer", "annual_salary": 180000, "currency": "USD"},
        )
        assert offer.status_code == 201
        wrong_order = client.post(
            f"/v1/offers/{offer.json()['id']}/approvals",
            headers=headers,
            json={"decision": "approved", "expected_version": 1},
        )
        assert wrong_order.status_code == 403
        manager_headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "manager"}
        step_one = client.post(
            f"/v1/offers/{offer.json()['id']}/approvals",
            headers=manager_headers,
            json={"decision": "approved", "expected_version": 1},
        )
        assert step_one.json()["status"] == "pending_approval"
        final = client.post(
            f"/v1/offers/{offer.json()['id']}/approvals",
            headers=headers,
            json={"decision": "approved", "expected_version": 2},
        )
    assert final.json()["status"] == "approved"
    assert final.json()["candidate_stage"] == "offer_approved"
