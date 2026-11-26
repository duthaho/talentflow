import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.models import CandidateCase, Membership, User
from app.shared.settings import Settings
from tests.integration.test_tenant_rbac import bootstrap_tenant

POSTGRES_URL = os.environ.get("DATABASE_URL")


@pytest.fixture(scope="module", params=["sqlite", "postgres"])
def search_context(request):
    if request.param == "postgres":
        if not POSTGRES_URL or not POSTGRES_URL.startswith("postgresql"):
            pytest.skip("requires the PostgreSQL DATABASE_URL used by the migration test job")
        database_url = POSTGRES_URL
    else:
        database_url = "sqlite://"
    app = create_app(
        database_url,
        Settings(app_env="test", auth_mode="development_headers", rate_limit_enabled=False),
    )
    suffix = uuid4().hex[:24]
    with TestClient(app) as client:
        tenant = bootstrap_tenant(client, f"search-{suffix}", f"admin-{suffix}")
        foreign = bootstrap_tenant(client, f"foreign-{suffix}", f"other-{suffix}")
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": f"admin-{suffix}"}
        requisitions = [
            client.post(
                "/v1/requisitions",
                headers=headers,
                json={"title": title, "department": "Engineering"},
            ).json()["id"]
            for title in ("Engineer", "Designer")
        ]
        with app.state.session_factory() as session:
            rows = [
                ("Ada", "Lovelace", "ada@example.test", "screening", requisitions[0]),
                ("Grace", "Hopper", "grace@example.test", "interviewing", requisitions[0]),
                ("Ada", "Other", "ada.other@example.test", "applied", requisitions[0]),
                ("Ada", "Design", "ada.design@example.test", "screening", requisitions[1]),
                ("Đặng", "Nguyễn", "vietnamese@example.test", "screening", requisitions[0]),
            ]
            for index, token in enumerate(["a%", "a_", "a\\", "a/", "a\\%", "aX", "a\\X"]):
                rows.append(
                    (
                        f"Token {token} end",
                        "Literal",
                        f"literal{index}@example.test",
                        "screening",
                        requisitions[0],
                    )
                )
            # All named matches sort beyond the old 100-row picker cap.
            for index in range(105):
                session.add(
                    CandidateCase(
                        id=f"{suffix}-0-{index:03}",
                        tenant_id=tenant["id"],
                        requisition_id=requisitions[0],
                        first_name="Filler",
                        last_name="Person",
                        email=f"filler{index}@example.test",
                        stage="screening",
                        created_by=headers["X-Actor-Id"],
                    )
                )
            for index, (first, last, email, stage, requisition) in enumerate(rows):
                session.add(
                    CandidateCase(
                        id=f"{suffix}-1-{index:03}",
                        tenant_id=tenant["id"],
                        requisition_id=requisition,
                        first_name=first,
                        last_name=last,
                        email=email,
                        stage=stage,
                        created_by=headers["X-Actor-Id"],
                    )
                )
            session.add(
                CandidateCase(
                    id=f"{suffix}-foreign",
                    tenant_id=foreign["id"],
                    requisition_id=requisitions[0],
                    first_name="Ada",
                    last_name="Lovelace",
                    email="foreign@example.test",
                    stage="screening",
                    created_by=f"other-{suffix}",
                )
            )
            session.add(User(id=f"interviewer-{suffix}"))
            session.add(
                Membership(
                    tenant_id=tenant["id"], user_id=f"interviewer-{suffix}", role="interviewer"
                )
            )
            session.commit()
        yield client, headers, requisitions, request.param, f"interviewer-{suffix}"


@pytest.mark.parametrize(
    ("q", "emails"),
    [
        ("loveLACE", {"ada@example.test"}),
        ("gRaCe", {"grace@example.test"}),
        ("aDa LoVe", {"ada@example.test"}),
        ("GRACE@EXAMPLE", {"grace@example.test"}),
        ("  loveLACE  ", {"ada@example.test"}),
        ("not-found", set()),
        ("a%", {"literal0@example.test"}),
        ("a_", {"literal1@example.test"}),
        ("a\\", {"literal2@example.test", "literal4@example.test", "literal6@example.test"}),
        ("a/", {"literal3@example.test"}),
        ("a\\%", {"literal4@example.test"}),
    ],
)
def test_candidate_search_matching_and_literal_escaping(search_context, q, emails):
    client, headers, _, _, _ = search_context
    response = client.get("/v1/candidate-cases", headers=headers, params={"q": q})
    assert response.status_code == 200, response.text
    assert {item["email"] for item in response.json()["items"]} == emails
    assert response.json()["total"] == len(emails)


def test_candidate_search_filters_pagination_and_tenant_count(search_context):
    client, headers, requisitions, _, _ = search_context
    params = {"q": "ada", "stage": "screening", "limit": 1}
    first = client.get("/v1/candidate-cases", headers=headers, params=params).json()
    assert first["total"] == 2
    assert first["next_cursor"] == first["items"][0]["id"]
    second = client.get(
        "/v1/candidate-cases", headers=headers, params={**params, "cursor": first["next_cursor"]}
    ).json()
    assert second["total"] == 2
    assert second["next_cursor"] is None
    assert {first["items"][0]["email"], second["items"][0]["email"]} == {
        "ada@example.test",
        "ada.design@example.test",
    }
    filtered = client.get(
        "/v1/candidate-cases", headers=headers, params={**params, "requisition_id": requisitions[0]}
    ).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["email"] == "ada@example.test"
    assert filtered["next_cursor"] is None
    plain = client.get(
        "/v1/candidate-cases", headers=headers, params={"stage": "screening", "limit": 100}
    ).json()
    assert len(plain["items"]) == 100
    assert all(item["first_name"] == "Filler" for item in plain["items"])
    assert plain["total"] == 115


@pytest.mark.parametrize("q", ["z", "z" * 101, "   ", "", "ab\x00", "ab\x7f", "ab\x85", "\tab"])
def test_invalid_search_is_private_problem_json(search_context, q):
    client, headers, _, _, _ = search_context
    response = client.get("/v1/candidate-cases", headers=headers, params={"q": q})
    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["type"].endswith("#validation-error")
    assert body["errors"][0]["pointer"] == "/q"
    # JSON escaping must not mask an echoed control character.
    if q:
        assert q not in json.dumps(body, ensure_ascii=False)
        assert all(q not in item["detail"] for item in body["errors"])


def test_search_permission_precedes_validation(search_context):
    client, headers, _, _, interviewer = search_context
    for q in ("ada", "x"):
        response = client.get(
            "/v1/candidate-cases", headers={**headers, "X-Actor-Id": interviewer}, params={"q": q}
        )
        assert response.status_code == 403


def test_postgres_search_folds_non_ascii_case(search_context):
    client, headers, _, backend, _ = search_context
    if backend != "postgres":
        pytest.skip("SQLite lower() only folds ASCII")
    response = client.get("/v1/candidate-cases", headers=headers, params={"q": "đẶNG"})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["email"] == "vietnamese@example.test"
    assert (
        client.get("/v1/candidate-cases", headers=headers, params={"q": "nguyen"}).json()["total"]
        == 0
    )
