"""Create repeatable local-only Keycloak and TalentFlow demo identities."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.shared.models import Membership, Tenant, User

TENANT_ID = "00000000-0000-4000-8000-000000000001"
USERS = (
    ("00000000-0000-4000-8000-000000000011", "admin@talentflow.local", "tenant_admin"),
    ("00000000-0000-4000-8000-000000000012", "recruiter@talentflow.local", "recruiter"),
    ("00000000-0000-4000-8000-000000000013", "manager@talentflow.local", "hiring_manager"),
    ("00000000-0000-4000-8000-000000000014", "interviewer@talentflow.local", "interviewer"),
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
    password = os.environ["DEMO_USER_PASSWORD"]
    for user_id, email, _role in USERS:
        payload = {
            "id": user_id,
            "username": email,
            "email": email,
            "enabled": True,
            "emailVerified": True,
            "attributes": {"tenant_id": [TENANT_ID]},
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        }
        user_url = f"{base_url}/admin/realms/talentflow/users/{user_id}"
        try:
            request_json(user_url, token=token)
        except HTTPError as error:
            if error.code != 404:
                raise
            request_json(
                f"{base_url}/admin/realms/talentflow/users",
                method="POST",
                payload=payload,
                token=token,
            )
        else:
            request_json(user_url, method="PUT", payload=payload, token=token)


def seed_database() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    with Session(engine) as session:
        tenant = session.get(Tenant, TENANT_ID)
        if tenant is None:
            session.add(Tenant(id=TENANT_ID, name="TalentFlow Demo", slug="talentflow-demo"))
        for user_id, email, role in USERS:
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
