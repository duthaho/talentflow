from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.problem_details import PROBLEM_TYPE_BASE, PROBLEM_TYPES
from app.shared.settings import Settings


def assert_problem(
    response, *, status: int, slug: str, correlation_id: str = "test-correlation"
) -> None:
    body = response.json()
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    assert body["type"] == f"{PROBLEM_TYPE_BASE}{slug}"
    assert body["status"] == status
    assert body["title"]
    assert body["detail"]
    assert body["instance"]
    assert body["correlation_id"] == correlation_id


def test_validation_errors_are_problem_details_with_field_pointers() -> None:
    with TestClient(create_app("sqlite://")) as client:
        response = client.post(
            "/v1/tenants",
            headers={"X-Correlation-Id": "test-correlation"},
            json={"name": "", "slug": "", "admin_id": ""},
        )

    assert_problem(response, status=422, slug="validation-error")
    assert {error["pointer"] for error in response.json()["errors"]} == {
        "/name",
        "/slug",
        "/admin_id",
    }


def test_auth_not_found_and_rate_limit_errors_are_problem_details() -> None:
    with TestClient(create_app("sqlite://")) as client:
        forbidden = client.get(
            "/v1/candidate-cases", headers={"X-Correlation-Id": "test-correlation"}
        )
        missing = client.get("/missing", headers={"X-Correlation-Id": "test-correlation"})

    app = create_app("sqlite://", app_settings=Settings(rate_limit_requests_per_minute=1))
    with TestClient(app) as client:
        client.get("/missing", headers={"X-Correlation-Id": "test-correlation"})
        limited = client.get("/missing", headers={"X-Correlation-Id": "test-correlation"})

    assert_problem(forbidden, status=403, slug="forbidden")
    assert_problem(missing, status=404, slug="not-found")
    assert_problem(limited, status=429, slug="rate-limited")
    assert limited.headers["retry-after"]


def test_unhandled_errors_hide_exception_details() -> None:
    app = create_app("sqlite://")

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("candidate@example.com secret stack detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert_problem(
        response,
        status=500,
        slug="internal-error",
        correlation_id=response.headers["x-correlation-id"],
    )
    assert response.json()["correlation_id"]
    assert "candidate@example.com" not in response.text
    assert "stack detail" not in response.text


def test_documentation_has_a_heading_for_each_registered_problem_type() -> None:
    documentation = Path("docs/api-errors.md").read_text()

    for slug in PROBLEM_TYPES:
        assert f"## {slug}\n" in documentation
