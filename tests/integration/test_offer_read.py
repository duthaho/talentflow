from datetime import datetime

from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.models import ApprovalDecision, Membership, OutboxEvent, User
from app.shared.problem_details import PROBLEM_TYPE_BASE


def _headers(tenant_id: str, actor_id: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-Actor-Id": actor_id}


def _create_tenant(client: TestClient, *, slug: str, admin_id: str) -> dict[str, str]:
    return client.post(
        "/v1/tenants", json={"name": slug, "slug": slug, "admin_id": admin_id}
    ).json()


def _add_roles(app, tenant_id: str) -> None:  # type: ignore[no-untyped-def]
    with app.state.session_factory() as session:
        session.add_all(
            [
                User(id="manager"),
                User(id="recruiter"),
                User(id="auditor"),
                User(id="interviewer"),
                Membership(tenant_id=tenant_id, user_id="manager", role="hiring_manager"),
                Membership(tenant_id=tenant_id, user_id="recruiter", role="recruiter"),
                Membership(tenant_id=tenant_id, user_id="auditor", role="auditor"),
                Membership(tenant_id=tenant_id, user_id="interviewer", role="interviewer"),
            ]
        )
        session.commit()


def _create_offer(client: TestClient, tenant_id: str, admin_id: str, number: int) -> dict[str, str]:
    headers = _headers(tenant_id, admin_id)
    requisition = client.post(
        "/v1/requisitions",
        headers=headers,
        json={"title": f"Engineer {number}", "department": "Engineering"},
    ).json()
    candidate = client.post(
        "/v1/candidate-cases",
        headers=headers,
        json={
            "requisition_id": requisition["id"],
            "first_name": "Ada",
            "last_name": str(number),
            "email": f"ada-{tenant_id[:4]}-{number}@example.com",
        },
    ).json()
    for stage, version in (("screening", 1), ("interviewing", 2)):
        assert (
            client.patch(
                f"/v1/candidate-cases/{candidate['id']}/stage",
                headers=headers,
                json={"target_stage": stage, "expected_version": version},
            ).status_code
            == 200
        )
    offer = client.post(
        f"/v1/candidate-cases/{candidate['id']}/offers",
        headers=headers,
        json={"title": f"Engineer {number}", "annual_salary": 120_000, "currency": "USD"},
    ).json()
    return {"id": offer["id"], "candidate_id": candidate["id"]}


def _approve_step_one(client: TestClient, tenant_id: str, offer_id: str, version: int = 1) -> None:
    response = client.post(
        f"/v1/offers/{offer_id}/approvals",
        headers=_headers(tenant_id, "manager"),
        json={"decision": "approved", "expected_version": version},
    )
    assert response.status_code == 200


def test_offer_inbox_is_role_and_tenant_scoped() -> None:
    app = create_app("sqlite://")
    with TestClient(app) as client:
        tenant_a = _create_tenant(client, slug="tenant-a", admin_id="admin-a")
        tenant_b = _create_tenant(client, slug="tenant-b", admin_id="admin-b")
        _add_roles(app, tenant_a["id"])
        pending = _create_offer(client, tenant_a["id"], "admin-a", 1)
        second_step = _create_offer(client, tenant_a["id"], "admin-a", 2)
        _approve_step_one(client, tenant_a["id"], second_step["id"])
        foreign = _create_offer(client, tenant_b["id"], "admin-b", 1)

        manager = client.get("/v1/offers?awaiting=me", headers=_headers(tenant_a["id"], "manager"))
        admin = client.get("/v1/offers?awaiting=me", headers=_headers(tenant_a["id"], "admin-a"))
        recruiter = client.get(
            "/v1/offers?awaiting=me", headers=_headers(tenant_a["id"], "recruiter")
        )
        auditor = client.get("/v1/offers?awaiting=me", headers=_headers(tenant_a["id"], "auditor"))

    assert {item["id"] for item in manager.json()["items"]} == {pending["id"]}
    assert {item["id"] for item in admin.json()["items"]} == {second_step["id"]}
    assert manager.json()["items"][0]["can_decide"] is True
    assert admin.json()["items"][0]["can_decide"] is True
    assert recruiter.json() == {"items": [], "next_cursor": None, "total": 0}
    assert auditor.json() == {"items": [], "next_cursor": None, "total": 0}
    assert foreign["id"] not in {item["id"] for item in manager.json()["items"]}


def test_offer_list_cursor_case_filter_and_invalid_filters() -> None:
    app = create_app("sqlite://")
    with TestClient(app) as client:
        tenant_a = _create_tenant(client, slug="cursor-a", admin_id="admin-a")
        tenant_b = _create_tenant(client, slug="cursor-b", admin_id="admin-b")
        _add_roles(app, tenant_a["id"])
        offers = [_create_offer(client, tenant_a["id"], "admin-a", number) for number in range(5)]
        foreign = _create_offer(client, tenant_b["id"], "admin-b", 1)
        headers = _headers(tenant_a["id"], "recruiter")
        first = client.get("/v1/offers?limit=2", headers=headers).json()
        second = client.get(
            f"/v1/offers?limit=2&cursor={first['next_cursor']}", headers=headers
        ).json()
        third = client.get(
            f"/v1/offers?limit=2&cursor={second['next_cursor']}", headers=headers
        ).json()
        by_case = client.get(
            f"/v1/offers?candidate_case_id={offers[0]['candidate_id']}", headers=headers
        ).json()
        foreign_case = client.get(
            f"/v1/offers?candidate_case_id={foreign['candidate_id']}", headers=headers
        ).json()

        invalid = [
            client.get("/v1/offers?awaiting=you", headers=headers),
            client.get("/v1/offers?status=draft", headers=headers),
            client.get("/v1/offers?limit=0", headers=headers),
            client.get("/v1/offers?cursor=" + "x" * 65, headers=headers),
            client.get("/v1/offers?candidate_case_id=" + "x" * 65, headers=headers),
        ]

    assert first["total"] == second["total"] == third["total"] == 5
    assert len({item["id"] for page in (first, second, third) for item in page["items"]}) == 5
    assert third["next_cursor"] is None
    assert by_case["items"][0]["id"] == offers[0]["id"]
    assert foreign_case == {"items": [], "next_cursor": None, "total": 0}
    assert all(response.status_code == 422 for response in invalid)


def test_offer_detail_reason_and_not_found_are_tenant_safe() -> None:
    app = create_app("sqlite://")
    with TestClient(app) as client:
        tenant_a = _create_tenant(client, slug="detail-a", admin_id="admin-a")
        tenant_b = _create_tenant(client, slug="detail-b", admin_id="admin-b")
        _add_roles(app, tenant_a["id"])
        offer = _create_offer(client, tenant_a["id"], "admin-a", 1)
        foreign = _create_offer(client, tenant_b["id"], "admin-b", 1)
        _approve_step_one(client, tenant_a["id"], offer["id"])
        rejected = client.post(
            f"/v1/offers/{offer['id']}/approvals",
            headers=_headers(tenant_a["id"], "admin-a"),
            json={"decision": "rejected", "expected_version": 2, "reason": "  Above band  "},
        )
        detail = client.get(
            f"/v1/offers/{offer['id']}", headers=_headers(tenant_a["id"], "recruiter")
        )
        unknown = client.get("/v1/offers/unknown", headers=_headers(tenant_a["id"], "recruiter"))
        hidden = client.get(
            f"/v1/offers/{foreign['id']}", headers=_headers(tenant_a["id"], "recruiter")
        )

    assert rejected.status_code == 200
    assert detail.headers["cache-control"] == "private, no-store"
    assert detail.json()["status"] == "rejected"
    assert detail.json()["awaiting_role"] is None
    assert detail.json()["can_decide"] is False
    assert [decision["reason"] for decision in detail.json()["decisions"]] == [None, "Above band"]
    assert all(
        datetime.fromisoformat(decision["decided_at"]).tzinfo is not None
        for decision in detail.json()["decisions"]
    )
    assert unknown.status_code == hidden.status_code == 404
    assert unknown.json()["type"] == hidden.json()["type"] == f"{PROBLEM_TYPE_BASE}not-found"
    assert {
        key: value
        for key, value in unknown.json().items()
        if key not in {"instance", "correlation_id"}
    } == {
        key: value
        for key, value in hidden.json().items()
        if key not in {"instance", "correlation_id"}
    }


def test_rejection_validation_is_atomic_and_interviewer_cannot_read() -> None:
    app = create_app("sqlite://")
    with TestClient(app) as client:
        tenant = _create_tenant(client, slug="validation", admin_id="admin")
        _add_roles(app, tenant["id"])
        offer = _create_offer(client, tenant["id"], "admin", 1)
        for reason in (None, "", "   ", "x" * 501):
            payload = {"decision": "rejected", "expected_version": 1}
            if reason is not None:
                payload["reason"] = reason
            assert (
                client.post(
                    f"/v1/offers/{offer['id']}/approvals",
                    headers=_headers(tenant["id"], "manager"),
                    json=payload,
                ).status_code
                == 422
            )
        detail = client.get(f"/v1/offers/{offer['id']}", headers=_headers(tenant["id"], "manager"))
        denied = client.get(
            f"/v1/offers/{offer['id']}", headers=_headers(tenant["id"], "interviewer")
        )
        with app.state.session_factory() as session:
            assert session.query(ApprovalDecision).count() == 0
            assert session.query(OutboxEvent).count() == 0

    assert detail.json()["version"] == 1
    assert denied.status_code == 403
