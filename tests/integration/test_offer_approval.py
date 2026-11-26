from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.models import Membership, User
from app.shared.problem_details import PROBLEM_TYPE_BASE


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
        manager_headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "manager"}
        inbox = client.get("/v1/offers?awaiting=me", headers=manager_headers)
        assert inbox.status_code == 200
        assert inbox.headers["cache-control"] == "private, no-store"
        assert inbox.json()["total"] == 1
        assert inbox.json()["items"][0]["can_decide"] is True
        detail = client.get(f"/v1/offers/{offer.json()['id']}", headers=manager_headers)
        assert detail.status_code == 200
        assert detail.json()["candidate_case_id"] == candidate["id"]
        assert detail.json()["decisions"] == []
        wrong_order = client.post(
            f"/v1/offers/{offer.json()['id']}/approvals",
            headers=headers,
            json={"decision": "approved", "expected_version": 1},
        )
        assert wrong_order.status_code == 403
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
        hired = client.patch(
            f"/v1/candidate-cases/{candidate['id']}/stage",
            headers=headers,
            json={"target_stage": "hired", "expected_version": 5},
        )
    assert final.json()["status"] == "approved"
    assert final.json()["candidate_stage"] == "offer_approved"
    assert hired.status_code == 200
    assert hired.json()["stage"] == "hired"


def test_offer_approval_rejects_a_stale_version_with_current_version() -> None:
    app = create_app("sqlite://")
    with TestClient(app) as client:
        tenant = client.post(
            "/v1/tenants", json={"name": "Acme HR", "slug": "acme", "admin_id": "admin"}
        ).json()
        admin_headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "admin"}
        with app.state.session_factory() as session:
            session.add_all(
                [
                    User(id="manager"),
                    Membership(tenant_id=tenant["id"], user_id="manager", role="hiring_manager"),
                ]
            )
            session.commit()
        requisition = client.post(
            "/v1/requisitions",
            headers=admin_headers,
            json={"title": "Staff Engineer", "department": "Engineering"},
        ).json()
        candidate = client.post(
            "/v1/candidate-cases",
            headers=admin_headers,
            json={
                "requisition_id": requisition["id"],
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ada@example.com",
            },
        ).json()
        for stage, version in (("screening", 1), ("interviewing", 2)):
            assert (
                client.patch(
                    f"/v1/candidate-cases/{candidate['id']}/stage",
                    headers=admin_headers,
                    json={"target_stage": stage, "expected_version": version},
                ).status_code
                == 200
            )
        offer = client.post(
            f"/v1/candidate-cases/{candidate['id']}/offers",
            headers=admin_headers,
            json={"title": "Staff Engineer", "annual_salary": 180000, "currency": "USD"},
        ).json()
        manager_headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "manager"}
        assert (
            client.post(
                f"/v1/offers/{offer['id']}/approvals",
                headers=manager_headers,
                json={"decision": "approved", "expected_version": 1},
            ).status_code
            == 200
        )
        stale = client.post(
            f"/v1/offers/{offer['id']}/approvals",
            headers=admin_headers,
            json={"decision": "approved", "expected_version": 1},
        )

    assert stale.status_code == 409
    assert stale.json()["type"] == f"{PROBLEM_TYPE_BASE}version-conflict"
    assert stale.json()["current_version"] == 2
