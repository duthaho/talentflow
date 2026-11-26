import base64
import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.settings import Settings

POSTGRES_URL = os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL or not POSTGRES_URL.startswith("postgresql"),
    reason="requires the PostgreSQL DATABASE_URL used by the migration test job",
)


def _cursor(interview_id: str) -> str:
    payload = {"s": "2026-01-01T00:00:00Z", "i": interview_id}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


@pytest.mark.parametrize(
    ("params", "expected_status"),
    [
        ({"interviewer": "unknown"}, 200),
        ({"cursor": _cursor("unknown")}, 200),
        ({"interviewer": "\x00"}, 200),
        ({"cursor": _cursor("\x00")}, 422),
    ],
    ids=["unknown-filter-control", "unknown-cursor-control", "nul-filter", "nul-cursor"],
)
def test_postgres_interview_input_contract(params: dict[str, str], expected_status: int) -> None:
    assert POSTGRES_URL is not None
    app = create_app(
        POSTGRES_URL,
        Settings(app_env="test", auth_mode="development_headers", rate_limit_enabled=False),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        suffix = uuid4().hex[:12]
        actor_id = f"postgres-qa-{suffix}"
        tenant = client.post(
            "/v1/tenants",
            json={
                "name": "PostgreSQL regression tenant",
                "slug": f"postgres-{suffix}",
                "admin_id": actor_id,
            },
        )
        assert tenant.status_code == 201
        response = client.get(
            "/v1/interviews",
            headers={"X-Tenant-Id": tenant.json()["id"], "X-Actor-Id": actor_id},
            params=params,
        )

    assert response.status_code == expected_status, response.text
    if expected_status == 200:
        assert response.json() == {"items": [], "next_cursor": None, "total": 0}
    else:
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["detail"] == "Invalid pagination cursor"
