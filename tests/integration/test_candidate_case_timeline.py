from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.modules.attachments.persistence import Attachment
from app.modules.audit.persistence import AuditEvent
from app.shared.models import Membership, User
from app.shared.problem_details import PROBLEM_TYPE_BASE
from app.shared.settings import Settings
from tests.case_timeline_cases import ALLOWLIST_ROWS, BAD_CURSORS, PII
from tests.integration.test_candidate_detail_read import _candidate
from tests.integration.test_tenant_rbac import bootstrap_tenant

BASE = datetime(2026, 1, 2, tzinfo=UTC)


@pytest.fixture
def context(tmp_path: Path):
    app = create_app("sqlite://", Settings(app_env="test", attachment_storage_root=str(tmp_path)))
    with TestClient(app) as client:
        tenant = bootstrap_tenant(client, "timeline-a", "admin-a")
        other = bootstrap_tenant(client, "timeline-b", "admin-b")
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "admin-a"}
        foreign_headers = {"X-Tenant-Id": other["id"], "X-Actor-Id": "admin-b"}
        case = _candidate(client, headers, "timeline-a@example.test")
        yield client, headers, foreign_headers, case


def _event(tenant: str, case: str, event_id: str, timestamp: datetime, **overrides) -> AuditEvent:
    values = dict(
        id=event_id,
        tenant_id=tenant,
        aggregate_type="candidate_case",
        aggregate_id=case,
        action="candidate_case.stage_transitioned",
        actor_id="admin-a",
        correlation_id="timeline-test",
        metadata_json={},
        created_at=timestamp,
    )
    return AuditEvent(**(values | overrides))


def _seven_events(client, headers, case) -> list[str]:
    # Keep the real creation event; give it and six synthetic rows controlled ordering.
    with client.app.state.session_factory() as session:
        created = session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == case["id"]))
        created.created_at = BASE - timedelta(days=1)
        for index in range(6):
            session.add(
                _event(
                    headers["X-Tenant-Id"],
                    case["id"],
                    f"event-{index}",
                    BASE + timedelta(seconds=index // 3),
                )
            )
        session.commit()
        return [f"event-{i}" for i in reversed(range(6))] + [created.id]


def _page(client, headers, case_id, **params):
    response = client.get(
        f"/v1/candidate-cases/{case_id}/audit-events", headers=headers, params=params
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    return response.json()


def _walk(client, headers, case_id, cursor=None):
    items = []
    for _ in range(10):
        params = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        page = _page(client, headers, case_id, **params)
        assert len(page["items"]) <= 3
        items.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            return items
        assert page["items"], "nonterminal page must make progress"
    pytest.fail("timeline cursor never terminated")


def test_limit_walk_orders_equal_timestamps_without_gaps_or_duplicates(context) -> None:
    client, headers, _, case = context
    expected = _seven_events(client, headers, case)
    items = _walk(client, headers, case["id"])
    assert [item["id"] for item in items] == expected
    keys = [(datetime.fromisoformat(item["occurred_at"]), item["id"]) for item in items]
    assert all(timestamp.utcoffset() == timedelta(0) for timestamp, _ in keys)
    assert keys == sorted(keys, reverse=True)
    assert len(set(item["id"] for item in items)) == 7


def test_old_cursor_remains_stable_after_two_stage_transitions(context) -> None:
    client, headers, _, case = context
    expected = _seven_events(client, headers, case)
    first = _page(client, headers, case["id"], limit=3)
    assert first["next_cursor"] is not None
    for version, stage in [(1, "screening"), (2, "interviewing")]:
        response = client.patch(
            f"/v1/candidate-cases/{case['id']}/stage",
            headers=headers,
            json={"target_stage": stage, "expected_version": version},
        )
        assert response.status_code == 200, response.text
    remaining = _walk(client, headers, case["id"], first["next_cursor"])
    assert [item["id"] for item in first["items"] + remaining] == expected
    latest = _page(client, headers, case["id"])
    assert len(latest["items"]) == 9
    assert latest["items"][0]["metadata"]["to_stage"] == "interviewing"


def _upload(client, headers, case_id):
    response = client.post(
        f"/v1/candidate-cases/{case_id}/attachments",
        headers=headers,
        data={"document_type": "resume"},
        files={"file": ("resume.pdf", b"%PDF-1.7\nresume", "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_timeline_includes_own_attachment_actions_and_excludes_other_aggregates(context) -> None:
    client, headers, _, case = context
    other = _candidate(client, headers, "other-case@example.test")
    attachment = _upload(client, headers, case["id"])
    foreign_attachment = _upload(client, headers, other["id"])
    download = client.get(
        f"/v1/candidate-cases/{case['id']}/attachments/{attachment['id']}/download",
        headers=headers,
    )
    assert download.status_code == 200
    with client.app.state.session_factory() as session:
        session.add(User(id="interviewer"))
        session.add(
            Membership(tenant_id=headers["X-Tenant-Id"], user_id="interviewer", role="interviewer")
        )
        session.commit()
    interview = client.post(
        f"/v1/candidate-cases/{case['id']}/interviews",
        headers=headers,
        json={"interviewer_id": "interviewer", "scheduled_at": "2026-12-01T09:00:00Z"},
    )
    assert interview.status_code == 201, interview.text
    # Prove the excluded action actually exists in the tenant audit trail.
    audit = client.get("/v1/audit-events", headers=headers)
    assert audit.status_code == 200
    assert any(item["action"].startswith("interview.") for item in audit.json())
    items = _walk(client, headers, case["id"])
    assert {(item["action"], item["aggregate_id"]) for item in items} == {
        ("candidate_case.created", case["id"]),
        ("candidate_attachment.uploaded", attachment["id"]),
        ("candidate_attachment.downloaded", attachment["id"]),
    }
    assert foreign_attachment["id"] not in {item["aggregate_id"] for item in items}


def test_attachment_join_requires_tenant_on_both_events_and_attachments(context) -> None:
    client, headers, foreign_headers, case = context
    own = _upload(client, headers, case["id"])
    foreign_case = _candidate(client, foreign_headers, "foreign@example.test")
    foreign = _upload(client, foreign_headers, foreign_case["id"])
    with client.app.state.session_factory() as session:
        # Inconsistent rows are intentional: the DB FK checks only case id, not tenant.
        record = session.get(Attachment, foreign["id"])
        record.candidate_case_id = case["id"]
        for event_id, tenant, attachment_id in [
            ("foreign-event-foreign-attachment", foreign_headers["X-Tenant-Id"], foreign["id"]),
            ("own-event-foreign-attachment", headers["X-Tenant-Id"], foreign["id"]),
            ("foreign-event-own-attachment", foreign_headers["X-Tenant-Id"], own["id"]),
        ]:
            session.add(
                _event(
                    tenant,
                    case["id"],
                    event_id,
                    BASE,
                    aggregate_type="candidate_attachment",
                    aggregate_id=attachment_id,
                    action="candidate_attachment.uploaded",
                    # Misleading JSON must never determine scope.
                    metadata_json={"candidate_case_id": case["id"]},
                )
            )
        session.commit()
    items = _walk(client, headers, case["id"])
    assert {(item["action"], item["aggregate_id"]) for item in items} == {
        ("candidate_case.created", case["id"]),
        ("candidate_attachment.uploaded", own["id"]),
    }


@pytest.mark.parametrize("destination", ["same-tenant-case", "other-tenant-case"])
def test_reusing_cursor_cannot_change_timeline_scope(context, destination: str) -> None:
    client, headers, foreign_headers, case = context
    _seven_events(client, headers, case)
    cursor = _page(client, headers, case["id"], limit=3)["next_cursor"]
    target_headers = headers if destination == "same-tenant-case" else foreign_headers
    target = _candidate(client, target_headers, "cursor-target@example.test")
    with client.app.state.session_factory() as session:
        created = session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == target["id"]))
        created.created_at = BASE - timedelta(days=1)
        session.add(_event(target_headers["X-Tenant-Id"], target["id"], "target-event", BASE))
        session.commit()
        expected = ["target-event", created.id]
    items = _page(client, target_headers, target["id"], cursor=cursor)["items"]
    assert [item["id"] for item in items] == expected
    assert all(item["aggregate_id"] == target["id"] for item in items)


def test_seeded_pii_never_appears_in_serialized_timeline(context) -> None:
    client, headers, _, case = context
    with client.app.state.session_factory() as session:
        for index, (action, metadata) in enumerate(ALLOWLIST_ROWS):
            session.add(
                _event(
                    headers["X-Tenant-Id"],
                    case["id"],
                    f"redact-{index}",
                    BASE,
                    action=action,
                    metadata_json={**metadata, **PII},
                )
            )
        session.add(
            _event(
                headers["X-Tenant-Id"],
                case["id"],
                "nested",
                BASE,
                action="candidate_case.created",
                metadata_json={"stage": {"email": PII["email"]}},
            )
        )
        session.commit()
    response = client.get(f"/v1/candidate-cases/{case['id']}/audit-events", headers=headers)
    assert response.status_code == 200
    for key, value in PII.items():
        assert f'"{key}"' not in response.text
        assert value not in response.text
    by_id = {item["id"]: item for item in response.json()["items"]}
    for index, (_, expected) in enumerate(ALLOWLIST_ROWS):
        assert by_id[f"redact-{index}"]["metadata"] == expected
    assert by_id["nested"]["metadata"] == {}


@pytest.mark.parametrize(
    "cursor", [value for _, value in BAD_CURSORS], ids=[name for name, _ in BAD_CURSORS]
)
def test_bad_cursors_are_422_problem_json(context, cursor: str) -> None:
    client, headers, _, case = context
    response = client.get(
        f"/v1/candidate-cases/{case['id']}/audit-events", headers=headers, params={"cursor": cursor}
    )
    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == f"{PROBLEM_TYPE_BASE}validation-error"


@pytest.mark.parametrize("limit", [0, 101])
def test_out_of_bounds_limit_is_422_problem_json(context, limit: int) -> None:
    client, headers, _, case = context
    response = client.get(
        f"/v1/candidate-cases/{case['id']}/audit-events", headers=headers, params={"limit": limit}
    )
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == f"{PROBLEM_TYPE_BASE}validation-error"
