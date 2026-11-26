"""Create repeatable local-only Keycloak and TalentFlow demo identities."""

from __future__ import annotations

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.shared.models import Membership, Tenant, User

TENANT_ID = "00000000-0000-4000-8000-000000000001"
USERS = (
    (
        "00000000-0000-4000-8000-000000000011",
        "admin@talentflow.local",
        "Admin",
        "Demo",
        "tenant_admin",
    ),
    (
        "00000000-0000-4000-8000-000000000012",
        "recruiter@talentflow.local",
        "Recruiter",
        "Demo",
        "recruiter",
    ),
    (
        "00000000-0000-4000-8000-000000000013",
        "manager@talentflow.local",
        "Manager",
        "Demo",
        "hiring_manager",
    ),
    (
        "00000000-0000-4000-8000-000000000014",
        "interviewer@talentflow.local",
        "Interviewer",
        "Demo",
        "interviewer",
    ),
)


def request_json(
    url: str, *, method: str = "GET", payload: object | None = None, token: str = ""
) -> object:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, data=data, headers=headers, method=method), timeout=15) as response:  # noqa: S310
        body = response.read()
    return json.loads(body) if body else {}


def admin_token(base_url: str) -> str:
    body = urlencode(
        {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": os.environ["KEYCLOAK_ADMIN_USERNAME"],
            "password": os.environ["KEYCLOAK_ADMIN_PASSWORD"],
        }
    ).encode()
    request = Request(
        f"{base_url}/realms/master/protocol/openid-connect/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urlopen(request, timeout=15) as response:  # noqa: S310
        return json.load(response)["access_token"]


def seed_keycloak() -> None:
    base_url = os.environ["KEYCLOAK_ADMIN_URL"]
    token = admin_token(base_url)
    web_base_url = os.environ["KEYCLOAK_WEB_BASE_URL"]
    clients = request_json(
        f"{base_url}/admin/realms/talentflow/clients?clientId=talentflow-api",
        token=token,
    )
    if not isinstance(clients, list) or len(clients) != 1:
        raise RuntimeError("Expected exactly one talentflow-api Keycloak client")
    client = clients[0]
    if not isinstance(client, dict) or not isinstance(client.get("id"), str):
        raise RuntimeError("Keycloak client response did not include an id")
    client["redirectUris"] = [f"{web_base_url}/auth/callback"]
    client["webOrigins"] = [web_base_url]
    attributes = client.setdefault("attributes", {})
    if not isinstance(attributes, dict):
        raise RuntimeError("Keycloak client attributes were not an object")
    attributes["post.logout.redirect.uris"] = f"{web_base_url}/signed-out"
    request_json(
        f"{base_url}/admin/realms/talentflow/clients/{client['id']}",
        method="PUT",
        payload=client,
        token=token,
    )
    password = os.environ["DEMO_USER_PASSWORD"]
    users = []
    for user_id, email, first_name, last_name, _role in USERS:
        users.append(
            {
                "id": user_id,
                "username": email,
                "email": email,
                "firstName": first_name,
                "lastName": last_name,
                "enabled": True,
                "emailVerified": True,
                "credentials": [{"type": "password", "value": password, "temporary": False}],
            }
        )
    request_json(
        f"{base_url}/admin/realms/talentflow/partialImport",
        method="POST",
        payload={"ifResourceExists": "OVERWRITE", "users": users},
        token=token,
    )


def seed_database() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    with Session(engine) as session:
        tenant = session.get(Tenant, TENANT_ID)
        if tenant is None:
            session.add(Tenant(id=TENANT_ID, name="TalentFlow Demo", slug="talentflow-demo"))
        for user_id, email, _first_name, _last_name, role in USERS:
            if session.get(User, user_id) is None:
                session.add(User(id=user_id, email=email))
            membership = session.scalar(
                select(Membership).where(
                    Membership.tenant_id == TENANT_ID, Membership.user_id == user_id
                )
            )
            if membership is None:
                session.add(Membership(tenant_id=TENANT_ID, user_id=user_id, role=role))
        session.commit()
    engine.dispose()


if __name__ == "__main__":
    seed_keycloak()
    seed_database()
    print("Seeded TalentFlow demo tenant and Keycloak users.")
