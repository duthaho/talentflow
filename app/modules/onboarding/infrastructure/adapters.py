"""No redirects, PII query strings, remote error messages or response logging."""

import time
from urllib.parse import quote

import httpx

from app.modules.onboarding.domain.policy import (
    AttemptTimeout,
    DirectoryConflict,
    PermanentStepError,
    TransientStepError,
)


async def request(client, method, url, **kwargs):
    try:
        response = await client.request(method, url, follow_redirects=False, **kwargs)
    except httpx.TimeoutException:
        raise AttemptTimeout() from None
    except httpx.HTTPError:
        raise TransientStepError() from None
    if response.status_code >= 500 or response.status_code in (408, 429):
        raise TransientStepError() from None
    return response


class HttpHris:
    def __init__(self, settings, transport=None):
        self.url = settings.hris_stub_url.rstrip("/")
        self.token = settings.hris_stub_token.get_secret_value()
        self.transport = transport

    async def call(self, method, key, **kwargs):
        async with httpx.AsyncClient(timeout=5, transport=self.transport) as client:
            response = await request(
                client,
                method,
                self.url + "/v1/employees/" + quote(key, safe=""),
                headers={"Authorization": "Bearer " + self.token},
                **kwargs,
            )
        if method == "DELETE" and response.status_code == 404:
            return None
        if not 200 <= response.status_code < 300:
            raise PermanentStepError("hris_rejected")
        return response

    async def upsert_employee(self, key, person):
        response = await self.call("PUT", key, json=person)
        try:
            return response.json()["employee_id"]
        except (ValueError, KeyError, TypeError):
            raise TransientStepError() from None

    async def delete_employee(self, key):
        await self.call("DELETE", key)


class KeycloakDirectory:
    def __init__(self, settings, transport=None):
        self.settings, self.transport = settings, transport
        self.token = None
        self.expiry = 0
        self.base = settings.keycloak_admin_url.rstrip("/")
        self.realm = quote(settings.keycloak_onboarding_realm, safe="")
        self.admin = f"{self.base}/admin/realms/{self.realm}"

    async def access_token(self, client):
        if self.token is None or time.monotonic() >= self.expiry:
            response = await request(
                client,
                "POST",
                f"{self.base}/realms/{self.realm}/protocol/openid-connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.settings.keycloak_onboarding_client_id,
                    "client_secret": self.settings.keycloak_onboarding_client_secret.get_secret_value(),
                },
            )
            if response.status_code != 200:
                raise TransientStepError()
            try:
                data = response.json()
                self.token = data["access_token"]
                self.expiry = time.monotonic() + max(0, data["expires_in"] - 30)
            except (ValueError, KeyError, TypeError):
                raise TransientStepError() from None
        return self.token

    async def call(self, client, method, path, **kwargs):
        for attempt in range(2):
            token = await self.access_token(client)
            response = await request(
                client,
                method,
                self.admin + path,
                headers={"Authorization": "Bearer " + token},
                **kwargs,
            )
            if response.status_code != 401 or attempt:
                break
            self.token = None
        return response

    async def owned(self, client, case_id, saga_id):
        response = await self.call(
            client,
            "GET",
            "/users",
            params={"username": "tf-" + case_id, "exact": "true", "briefRepresentation": "false"},
        )
        if response.status_code != 200:
            raise TransientStepError()
        try:
            users = response.json()
        except ValueError:
            raise TransientStepError() from None
        if not isinstance(users, list):
            raise TransientStepError()
        if (
            len(users) == 1
            and users[0].get("username") == "tf-" + case_id
            and users[0].get("attributes", {}).get("onboarding_saga_id") == [saga_id]
        ):
            return users[0]["id"]
        return None

    async def provision_user(self, case_id, saga_id, person):
        async with httpx.AsyncClient(timeout=5, transport=self.transport) as client:
            response = await self.call(
                client,
                "POST",
                "/users",
                json={
                    "username": "tf-" + case_id,
                    "enabled": False,
                    "emailVerified": False,
                    "email": person["email"],
                    "firstName": person["first_name"],
                    "lastName": person["last_name"],
                    "attributes": {
                        "onboarding_saga_id": [saga_id],
                        "talentflow_tenant_id": [person["tenant_id"]],
                    },
                },
            )
            if response.status_code not in (201, 409):
                raise PermanentStepError("directory_rejected")
            # Confirm ownership even after create: undeclared attributes must fail visibly.
            ident = await self.owned(client, case_id, saga_id)
            if ident is None:
                raise DirectoryConflict()
            return ident

    async def delete_user(self, case_id, saga_id):
        async with httpx.AsyncClient(timeout=5, transport=self.transport) as client:
            ident = await self.owned(client, case_id, saga_id)
            if ident is None:
                return
            response = await self.call(client, "DELETE", "/users/" + quote(ident, safe=""))
            if response.status_code not in (204, 404):
                raise TransientStepError()
