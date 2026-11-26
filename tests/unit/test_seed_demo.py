"""Tests for local demo identity seeding."""

from __future__ import annotations

from scripts import seed_demo


def test_seed_keycloak_updates_client_urls_for_selected_web_port(monkeypatch) -> None:
    monkeypatch.setenv("KEYCLOAK_ADMIN_URL", "http://keycloak:8080")
    monkeypatch.setenv("KEYCLOAK_WEB_BASE_URL", "http://localhost:13000")
    monkeypatch.setenv("DEMO_USER_PASSWORD", "test-password")
    monkeypatch.setattr(seed_demo, "admin_token", lambda _base_url: "admin-token")
    requests: list[tuple[str, str, object | None]] = []

    def fake_request_json(
        url: str, *, method: str = "GET", payload: object | None = None, token: str = ""
    ) -> object:
        assert token == "admin-token"
        requests.append((url, method, payload))
        if url.endswith("clients?clientId=talentflow-api"):
            return [{"id": "client-id", "attributes": {}}]
        return {}

    monkeypatch.setattr(seed_demo, "request_json", fake_request_json)

    seed_demo.seed_keycloak()

    client_update = requests[1]
    assert client_update[0].endswith("clients/client-id")
    assert client_update[1] == "PUT"
    assert client_update[2] == {
        "id": "client-id",
        "redirectUris": ["http://localhost:13000/auth/callback"],
        "webOrigins": ["http://localhost:13000"],
        "attributes": {"post.logout.redirect.uris": "http://localhost:13000/signed-out"},
    }
