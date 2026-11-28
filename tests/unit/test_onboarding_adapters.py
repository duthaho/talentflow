import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from app.modules.onboarding.domain.policy import (
    AttemptTimeout,
    DirectoryConflict,
    PermanentStepError,
    TransientStepError,
)
from app.modules.onboarding.infrastructure.adapters import HttpHris, KeycloakDirectory
from app.modules.onboarding.infrastructure.settings import OnboardingSettings
from app.workers.hris_stub import create_app


@pytest.mark.parametrize(
    "env,faults", [("production", "notify"), ("future", "notify"), ("test", "unknown")]
)
def test_faults_fail_closed(env, faults):
    with pytest.raises(ValueError):
        OnboardingSettings(app_env=env, onboarding_fault_injection=faults)


def test_production_credentials_and_urls():
    with pytest.raises(ValueError):
        OnboardingSettings(app_env="production")
    options = {
        "app_env": "production",
        "keycloak_onboarding_client_secret": "private-directory",
        "hris_stub_token": "private-hris",
    }
    with pytest.raises(ValueError):
        OnboardingSettings(**options)
    settings = OnboardingSettings(
        **options, keycloak_admin_url="https://directory.test", hris_stub_url="https://hris.test"
    )
    assert (
        "private-directory" not in repr(settings) + settings.model_dump_json()
        and "private-hris" not in repr(settings) + settings.model_dump_json()
    )


def test_compose_and_realm_privilege_boundary():
    services = yaml.safe_load(Path("docker-compose.yml").read_text())["services"]
    for name, service in services.items():
        env = service.get("environment", {})
        if name != "onboarding-worker":
            assert not any(k.startswith("KEYCLOAK_ONBOARDING_") for k in env)
        if name not in {"onboarding-worker", "hris-stub"}:
            assert not any(k.startswith("HRIS_STUB_") for k in env)
    assert "KEYCLOAK_ADMIN_PASSWORD" not in services["onboarding-worker"]["environment"]
    assert "ports" not in services["hris-stub"]
    realm = json.loads(Path("keycloak/realm-employees.json").read_text())
    assert not realm["registrationAllowed"] and realm["accessTokenLifespan"] <= 300
    assert realm["adminEventsEnabled"] and not realm["adminEventsDetailsEnabled"]
    client = realm["clients"][0]
    assert not any(
        client[k]
        for k in (
            "publicClient",
            "standardFlowEnabled",
            "directAccessGrantsEnabled",
            "implicitFlowEnabled",
        )
    )
    assert client["serviceAccountsEnabled"]
    assert realm["users"][0]["clientRoles"] == {"realm-management": ["manage-users"]}


def test_stub_auth_and_idempotency():
    with TestClient(create_app("private-token")) as client:
        path = "/v1/employees/" + str(uuid4())
        person = {
            "tenant_id": str(uuid4()),
            "candidate_case_id": str(uuid4()),
            "first_name": "PrivateName",
            "last_name": "PrivateLast",
            "email": "private@example.test",
            "start_date": "2026-12-12",
        }
        assert client.put(path, json=person).status_code == 401
        headers = {"Authorization": "Bearer private-token"}
        first = client.put(path, json=person, headers=headers)
        second = client.put(path, json=person, headers=headers)
        assert first.status_code == 201 and second.status_code == 200
        assert first.json()["employee_id"] == second.json()["employee_id"]
        assert client.get(path, headers=headers).status_code == 200
        assert client.delete(path, headers=headers).status_code == 204
        assert client.delete(path, headers=headers).status_code == 404


@pytest.mark.parametrize(
    "status,expected",
    [
        (400, PermanentStepError),
        (409, PermanentStepError),
        (302, PermanentStepError),
        (500, TransientStepError),
        (429, TransientStepError),
    ],
)
def test_hris_maps_errors_without_pii(status, expected, caplog):
    def handler(request):
        assert "email=" not in str(request.url)
        return httpx.Response(status, text="PrivateName private@example.test")

    adapter = HttpHris(OnboardingSettings(), httpx.MockTransport(handler))
    with pytest.raises(expected) as error:
        asyncio.run(adapter.upsert_employee(str(uuid4()), {}))
    assert "PrivateName" not in str(error.value) + caplog.text
    assert "private@example.test" not in str(error.value) + caplog.text


def test_timeout_and_no_redirect_following():
    def handler(request):
        raise httpx.ReadTimeout("PrivateName private@example.test")

    with pytest.raises(AttemptTimeout) as error:
        asyncio.run(
            HttpHris(OnboardingSettings(), httpx.MockTransport(handler)).upsert_employee(
                str(uuid4()), {}
            )
        )
    assert "PrivateName" not in str(error.value)


@pytest.mark.parametrize(
    "users",
    [
        [],
        [{"id": "foreign", "username": "tf-case", "attributes": {}}],
        [{"id": "similar", "username": "tf-casex", "attributes": {"onboarding_saga_id": ["saga"]}}],
        [{"id": "one"}, {"id": "two"}],
    ],
)
def test_directory_never_adopts_or_deletes_unowned_user(users):
    calls = []

    def handler(request):
        calls.append((request.method, str(request.url)))
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "token", "expires_in": 300})
        if request.method == "POST":
            return httpx.Response(409, text="PrivateName")
        if request.method == "GET":
            assert request.url.params["exact"] == "true"
            assert request.url.params["username"] == "tf-case"
            return httpx.Response(200, json=users)
        raise AssertionError("must not delete")

    adapter = KeycloakDirectory(OnboardingSettings(), httpx.MockTransport(handler))
    person = {
        "email": "private@example.test",
        "first_name": "PrivateName",
        "last_name": "Last",
        "tenant_id": str(uuid4()),
    }
    with pytest.raises(DirectoryConflict):
        asyncio.run(adapter.provision_user("case", "saga", person))
    asyncio.run(adapter.delete_user("case", "saga"))
    assert not any("email=" in url for _, url in calls)


def test_directory_token_refresh_is_bounded_and_secret_free(monkeypatch, caplog):
    from app.modules.onboarding.infrastructure import adapters

    ticks = [0]
    monkeypatch.setattr(adapters.time, "monotonic", lambda: ticks[0])
    count = [0]

    def handler(request):
        count[0] += 1
        return httpx.Response(200, json={"access_token": "private-access-token", "expires_in": 300})

    adapter = KeycloakDirectory(OnboardingSettings(), httpx.MockTransport(handler))

    async def use():
        async with httpx.AsyncClient(transport=adapter.transport) as client:
            assert await adapter.access_token(client) == "private-access-token"
            ticks[0] = 269
            await adapter.access_token(client)
            assert count[0] == 1
            ticks[0] = 270
            await adapter.access_token(client)
            assert count[0] == 2

    asyncio.run(use())
    assert "private-access-token" not in caplog.text
    assert "dev-onboarding-client-secret" not in caplog.text
