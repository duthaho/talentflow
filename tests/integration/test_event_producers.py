from pathlib import Path

import jsonschema
import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.shared.events import envelope
from app.shared.models import Membership, OutboxEvent, User

CATALOG = yaml.safe_load(Path("docs/events/asyncapi.yaml").read_text())


def validate(event):
    message = next(
        m for m in CATALOG["components"]["messages"].values() if m["name"] == event["type"]
    )
    # Resolve local references against the exact catalog used by other consumers.
    schema = {**message["payload"], "components": CATALOG["components"]}
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        event
    )


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_hiring_commands_emit_catalog_valid_events_with_atomic_stage_changes(decision):
    app = create_app("sqlite://")
    with TestClient(app) as client:
        tenant = client.post(
            "/v1/tenants", json={"name": "Events", "slug": "events", "admin_id": "admin"}
        ).json()["id"]
        headers = {"X-Tenant-Id": tenant, "X-Actor-Id": "admin", "X-Correlation-Id": "events-test"}
        with app.state.session_factory.begin() as session:
            session.add_all([User(id="manager"), User(id="interviewer")])
            session.flush()
            session.add_all(
                [
                    Membership(tenant_id=tenant, user_id="manager", role="hiring_manager"),
                    Membership(tenant_id=tenant, user_id="interviewer", role="interviewer"),
                ]
            )
        req = client.post(
            "/v1/requisitions", headers=headers, json={"title": "Engineer", "department": "Eng"}
        ).json()
        case = client.post(
            "/v1/candidate-cases",
            headers=headers,
            json={
                "requisition_id": req["id"],
                "first_name": "Private",
                "last_name": "Name",
                "email": "private@example.test",
            },
        ).json()
        for version, target in enumerate(("screening", "interviewing"), 1):
            response = client.patch(
                f"/v1/candidate-cases/{case['id']}/stage",
                headers=headers,
                json={"target_stage": target, "expected_version": version},
            )
            assert response.status_code == 200
        interview = client.post(
            f"/v1/candidate-cases/{case['id']}/interviews",
            headers=headers,
            json={
                "candidate_case_id": case["id"],
                "interviewer_id": "interviewer",
                "scheduled_at": "2027-01-01T10:00:00"
                if decision == "approved"
                else "2027-01-01T10:00:00Z",
            },
        )
        assert interview.status_code == 201, interview.text
        response = client.post(
            f"/v1/interviews/{interview.json()['id']}/feedback",
            headers={**headers, "X-Actor-Id": "interviewer"},
            json={"score": 4, "recommendation": "hire", "comments": "Private feedback"},
        )
        assert response.status_code == 201, response.text
        offer = client.post(
            f"/v1/candidate-cases/{case['id']}/offers",
            headers=headers,
            json={"title": "Private title", "annual_salary": 180000, "currency": "USD"},
        ).json()
        response = client.post(
            f"/v1/offers/{offer['id']}/approvals",
            headers={**headers, "X-Actor-Id": "manager"},
            json={
                "decision": decision,
                "expected_version": 1,
                **({"reason": "Private rejection"} if decision == "rejected" else {}),
            },
        )
        assert response.status_code == 200, response.text
        if decision == "approved":
            response = client.post(
                f"/v1/offers/{offer['id']}/approvals",
                headers=headers,
                json={"decision": "approved", "expected_version": 2},
            )
            assert response.status_code == 200, response.text
        with app.state.session_factory() as session:
            events = list(session.scalars(select(OutboxEvent)))
            assert {event.topic for event in events} == {
                "candidate_case.created.v1",
                "candidate_case.stage_changed.v1",
                "interview.scheduled.v1",
                "interview.feedback_submitted.v1",
                "offer.created.v1",
                "offer.approval_recorded.v1",
            }
            for event in events:
                body = envelope(event)
                validate(body)
                assert body["correlationid"] == body["causationid"] == "events-test"
                assert body["tenantid"] == tenant
                assert "actorid" in body
                assert "Private" not in str(body)
                assert "180000" not in str(body)
            stages = [e for e in events if e.topic == "candidate_case.stage_changed.v1"]
            assert len(stages) == 4
            assert stages[-1].payload_json["to_stage"] == (
                "offer_approved" if decision == "approved" else "offer_rejected"
            )
            assert all(e.payload_json["offer_id"] == offer["id"] for e in stages[2:])
        # Conflicts must produce no additional events or phantom business changes.
        conflict = client.patch(
            f"/v1/candidate-cases/{case['id']}/stage",
            headers=headers,
            json={"target_stage": "withdrawn", "expected_version": 1},
        )
        assert conflict.status_code == 409
        with app.state.session_factory() as session:
            assert session.query(OutboxEvent).count() == len(events)
