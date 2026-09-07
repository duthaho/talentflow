from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.models import Membership, User


def test_offer_decision_and_outbox_event_are_transactionally_recorded() -> None:
    app = create_app("sqlite://")
    with TestClient(app) as client:
        tenant = client.post(
            "/v1/tenants", json={"name": "Acme", "slug": "acme", "admin_id": "admin"}
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
        requisition = client.post(
            "/v1/requisitions",
            headers=headers,
            json={"title": "Staff Engineer", "department": "Eng"},
        ).json()
        candidate = client.post(
            "/v1/candidate-cases",
            headers=headers,
            json={
                "requisition_id": requisition["id"],
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
        ).json()
        decision = client.post(
            f"/v1/offers/{offer['id']}/approvals",
            headers={"X-Tenant-Id": tenant["id"], "X-Actor-Id": "manager"},
            json={"decision": "approved", "expected_version": 1},
        )
        assert decision.status_code == 200
        with app.state.session_factory() as session:
            from app.shared.models import ApprovalDecision, OutboxEvent

            assert session.query(ApprovalDecision).count() == 1
            event = session.query(OutboxEvent).one()
            assert event.topic == "offer.approval_recorded.v1"
            assert event.payload_json["decision"] == "approved"
