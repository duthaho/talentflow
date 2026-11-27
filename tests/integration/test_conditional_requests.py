import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.candidates.infrastructure.sqlalchemy_repository import (
    SqlAlchemyCandidateRepository,
)
from app.modules.offers.infrastructure.sqlalchemy_repository import SqlAlchemyOfferRepository
from app.shared.models import ApprovalDecision, AuditEvent, Membership, OutboxEvent, User
from app.shared.problem_details import PROBLEM_TYPE_BASE
from app.shared.settings import Settings


@pytest.fixture(params=["candidate", "offer"])
def resource(request):
    app = create_app("sqlite://", Settings(app_env="test", rate_limit_enabled=False))
    with TestClient(app) as client:
        tenant = client.post(
            "/v1/tenants", json={"name": "Conditional", "slug": "conditional", "admin_id": "admin"}
        ).json()
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "admin"}
        requisition = client.post(
            "/v1/requisitions",
            headers=headers,
            json={"title": "Engineer", "department": "Engineering"},
        ).json()
        candidate = client.post(
            "/v1/candidate-cases",
            headers=headers,
            json={
                "requisition_id": requisition["id"],
                "first_name": "Ada",
                "last_name": "Test",
                "email": "ada@example.test",
            },
        ).json()
        detail_path = f"/v1/candidate-cases/{candidate['id']}"
        method, command_path, payload = (
            "PATCH",
            detail_path + "/stage",
            {"target_stage": "screening"},
        )
        if request.param == "offer":
            for version, stage in ((1, "screening"), (2, "interviewing")):
                response = client.patch(
                    command_path,
                    headers=headers,
                    json={"target_stage": stage, "expected_version": version},
                )
                assert response.status_code == 200, response.text
            offer = client.post(
                detail_path + "/offers",
                headers=headers,
                json={"title": "Engineer", "annual_salary": 120000, "currency": "USD"},
            ).json()
            with app.state.session_factory() as session:
                session.add(User(id="manager"))
                session.add(
                    Membership(tenant_id=tenant["id"], user_id="manager", role="hiring_manager")
                )
                session.commit()
            headers = {**headers, "X-Actor-Id": "manager"}
            detail_path = f"/v1/offers/{offer['id']}"
            method, command_path, payload = (
                "POST",
                detail_path + "/approvals",
                {"decision": "approved"},
            )
        yield app, client, headers, detail_path, method, command_path, payload


def write(resource, *, tag=None, version=None, key=None):
    _, client, headers, _, method, path, payload = resource
    if tag is not None:
        headers = {**headers, "If-Match": tag}
    if version is not None:
        payload = {**payload, "expected_version": version}
    if key is not None:
        headers = {**headers, "Idempotency-Key": key}
    return client.request(method, path, headers=headers, json=payload)


def assert_problem(response, status, slug):
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == PROBLEM_TYPE_BASE + slug
    assert response.json()["status"] == status
    assert response.json()["correlation_id"]


def test_read_and_conditional_write_return_version_etags(resource):
    _, client, headers, path, *_ = resource
    read = client.get(path, headers=headers)
    assert read.status_code == 200
    assert read.headers["ETag"] == '"1"'
    success = write(resource, tag=read.headers["ETag"])
    assert success.status_code == 200, success.text
    assert success.headers["ETag"] == '"2"'
    assert success.json()["version"] == 2
    assert client.get(path, headers=headers).headers["ETag"] == '"2"'


def test_stale_header_returns_problem_and_current_etag(resource):
    assert write(resource, tag='"1"').status_code == 200
    stale = write(resource, tag='"1"')
    assert_problem(stale, 412, "precondition-failed")
    assert stale.headers["ETag"] == '"2"'
    assert stale.json()["current_version"] == 2
    assert stale.json()["title"] == "Precondition Failed"


def test_missing_precondition_is_428(resource):
    response = write(resource)
    assert_problem(response, 428, "precondition-required")
    assert response.headers["Cache-Control"] == "no-store"


def test_disagreeing_preconditions_are_400(resource):
    assert_problem(write(resource, tag='"1"', version=2), 400, "invalid-precondition")


@pytest.mark.parametrize("tag", ['"1"', "*", '"opaque", "1"'])
def test_agreeing_body_and_header_succeed(resource, tag):
    assert write(resource, tag=tag, version=1).status_code == 200


@pytest.mark.parametrize("tag", ["*", '"missing", "1"', ' "1" ', '"one,two", "1"'])
def test_wildcard_and_strong_tag_alternatives(resource, tag):
    assert write(resource, tag=tag).status_code == 200


@pytest.mark.parametrize("tag", ['W/"1"', "1", "", '"1",', '*, "1"', '"a b"', '"1", W/"2"'])
def test_malformed_header_is_400(resource, tag):
    assert_problem(write(resource, tag=tag), 400, "invalid-precondition")


def test_opaque_nonmatching_tag_is_a_failed_precondition(resource):
    assert_problem(write(resource, tag='"other"'), 412, "precondition-failed")


def test_legacy_body_still_uses_409(resource):
    assert write(resource, version=1).status_code == 200
    assert_problem(write(resource, version=1), 409, "version-conflict")


def test_matching_stale_body_and_header_use_412(resource):
    assert write(resource, version=1).status_code == 200
    assert_problem(write(resource, tag='"1"', version=1), 412, "precondition-failed")


def test_wildcard_does_not_discard_stale_body_version(resource):
    assert_problem(write(resource, tag="*", version=2), 412, "precondition-failed")


def test_idempotent_replay_precedes_version_check_and_preserves_etag(resource):
    app, client, headers, path, *_ = resource
    first = write(resource, tag='"1"', key="retry")
    assert first.status_code == 200, first.text
    # Advance the aggregate again so the stored ETag is distinguishable from the current one.
    if "/offers/" in path:
        next_headers = {**headers, "X-Actor-Id": "admin"}
        next_payload = {"decision": "approved"}
        method, suffix = "POST", "/approvals"
    else:
        next_headers, next_payload = headers, {"target_stage": "interviewing"}
        method, suffix = "PATCH", "/stage"
    assert (
        client.request(
            method, path + suffix, headers={**next_headers, "If-Match": '"2"'}, json=next_payload
        ).status_code
        == 200
    )
    with app.state.session_factory() as session:
        counts = [
            session.query(model).count() for model in (AuditEvent, ApprovalDecision, OutboxEvent)
        ]
    replay = write(resource, tag='"1"', key="retry")
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert replay.headers["ETag"] == first.headers["ETag"] == '"2"'
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert client.get(path, headers=headers).headers["ETag"] == '"3"'
    with app.state.session_factory() as session:
        assert [
            session.query(model).count() for model in (AuditEvent, ApprovalDecision, OutboxEvent)
        ] == counts
    assert_problem(write(resource, tag='"3"', key="retry"), 422, "validation-error")


def test_failed_precondition_releases_idempotency_key(resource):
    assert write(resource, tag='"0"', key="retry").status_code == 412
    assert write(resource, tag='"1"', key="retry").status_code == 200


def test_concurrent_repository_conflict_maps_to_412(resource, monkeypatch):
    app, client, headers, path, *_ = resource
    if "/offers/" in path:
        monkeypatch.setattr(SqlAlchemyOfferRepository, "update", lambda *args, **kwargs: False)
    else:
        monkeypatch.setattr(
            SqlAlchemyCandidateRepository, "transition", lambda *args, **kwargs: False
        )
    response = write(resource, tag='"1"')
    assert_problem(response, 412, "precondition-failed")
    assert response.headers["ETag"] == '"1"'
    assert client.get(path, headers=headers).json()["version"] == 1
    if "/offers/" in path:
        monkeypatch.undo()
        assert write(resource, tag='"1"').status_code == 200
        with app.state.session_factory() as session:
            counts = [session.query(model).count() for model in (ApprovalDecision, OutboxEvent)]
        # Final approval updates the offer before transitioning the candidate.
        monkeypatch.setattr(
            SqlAlchemyCandidateRepository, "transition", lambda *args, **kwargs: False
        )
        failure = client.post(
            path + "/approvals",
            headers={**headers, "X-Actor-Id": "admin", "If-Match": '"2"'},
            json={"decision": "approved"},
        )
        assert_problem(failure, 412, "precondition-failed")
        assert failure.headers["ETag"] == '"2"'
        detail = client.get(path, headers=headers).json()
        assert detail["version"] == 2
        assert detail["status"] == "pending_approval"
        with app.state.session_factory() as session:
            assert [
                session.query(model).count() for model in (ApprovalDecision, OutboxEvent)
            ] == counts


def test_conditions_do_not_expose_other_tenants(resource):
    _, client, _, path, method, command_path, payload = resource
    tenant = client.post(
        "/v1/tenants", json={"name": "Other", "slug": "other", "admin_id": "other-admin"}
    ).json()
    headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "other-admin"}
    for response in (
        client.get(path, headers=headers),
        client.request(method, command_path, headers={**headers, "If-Match": "*"}, json=payload),
    ):
        assert response.status_code == 404
        assert "ETag" not in response.headers


def test_repeated_header_fields_are_combined(resource):
    _, client, headers, _, method, path, payload = resource
    response = client.request(
        method,
        path,
        headers=[*headers.items(), ("If-Match", '"0"'), ("If-Match", '"1"')],
        json=payload,
    )
    assert response.status_code == 200, response.text


def test_openapi_describes_conditional_contract(resource):
    _, client, _, path, method, *_ = resource
    schema = client.get("/openapi.json").json()
    template = (
        "/v1/offers/{offer_id}" if "/offers/" in path else "/v1/candidate-cases/{candidate_case_id}"
    )
    suffix = "/approvals" if method == "POST" else "/stage"
    assert "ETag" in schema["paths"][template]["get"]["responses"]["200"]["headers"]
    operation = schema["paths"][template + suffix][method.lower()]
    assert any(p["name"] == "If-Match" and not p["required"] for p in operation["parameters"])
    for code in ("400", "412", "428"):
        assert "application/problem+json" in operation["responses"][code]["content"]
    assert "ETag" in operation["responses"]["412"]["headers"]
    model = "ApproveOfferRequest" if method == "POST" else "TransitionCandidateCaseRequest"
    assert "expected_version" not in schema["components"]["schemas"][model]["required"]


def test_cors_allows_precondition_and_exposes_etag():
    app = create_app(
        "sqlite://", Settings(app_env="test", cors_allowed_origins="https://example.test")
    )
    with TestClient(app) as client:
        preflight = client.options(
            "/v1/offers/offer/approvals",
            headers={
                "Origin": "https://example.test",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "If-Match, Idempotency-Key, Content-Type",
            },
        )
        assert preflight.status_code == 200
        assert "If-Match" in preflight.headers["Access-Control-Allow-Headers"]
        response = client.get("/health/live", headers={"Origin": "https://example.test"})
        assert "ETag" in response.headers["Access-Control-Expose-Headers"]
