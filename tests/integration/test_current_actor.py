from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.identity.application.authentication import (
    AuthenticatedPrincipal,
    AuthenticationError,
)
from app.modules.identity.security import ROLE_PERMISSIONS
from app.modules.organization.persistence import Membership, Tenant, User
from app.shared.settings import Settings

TENANT_ID = "00000000-0000-4000-8000-000000000001"
DEMO_USERS = (
    ("00000000-0000-4000-8000-000000000011", "admin@talentflow.local", "tenant_admin"),
    ("00000000-0000-4000-8000-000000000012", "recruiter@talentflow.local", "recruiter"),
    ("00000000-0000-4000-8000-000000000013", "manager@talentflow.local", "hiring_manager"),
    ("00000000-0000-4000-8000-000000000014", "interviewer@talentflow.local", "interviewer"),
)


class FakeValidator:
    def __init__(self, principals: dict[str, AuthenticatedPrincipal]) -> None:
        self.principals = principals

    def validate(self, token: str) -> AuthenticatedPrincipal:
        try:
            return self.principals[token]
        except KeyError as error:
            raise AuthenticationError("Invalid bearer token") from error


def oidc_settings() -> Settings:
    return Settings(
        auth_mode="oidc_jwt",
        oidc_issuer="https://issuer.example",
        oidc_audience="talentflow",
        oidc_jwks_url="https://issuer.example/jwks",
    )


def seed_demo_users(app) -> None:
    with app.state.session_factory() as session:
        session.add(Tenant(id=TENANT_ID, name="TalentFlow Demo", slug="talentflow-demo"))
        for user_id, email, role in DEMO_USERS:
            session.add(User(id=user_id, email=email))
            session.add(Membership(tenant_id=TENANT_ID, user_id=user_id, role=role))
        session.commit()


def test_current_actor_returns_each_seeded_role_and_permissions() -> None:
    app = create_app("sqlite://", oidc_settings())
    with TestClient(app) as client:
        seed_demo_users(app)
        app.state.token_validator = FakeValidator(
            {
                user_id: AuthenticatedPrincipal(subject=user_id, tenant_id=TENANT_ID)
                for user_id, _, _ in DEMO_USERS
            }
        )
        for user_id, email, role in DEMO_USERS:
            response = client.get("/v1/me", headers={"Authorization": f"Bearer {user_id}"})
            assert response.status_code == 200
            assert response.json() == {
                "user_id": user_id,
                "email": email,
                "display_name": None,
                "tenant_id": TENANT_ID,
                "tenant_name": "TalentFlow Demo",
                "role": role,
                "permissions": sorted(ROLE_PERMISSIONS[role]),
            }


def test_current_actor_rejects_missing_invalid_or_non_member_callers() -> None:
    app = create_app("sqlite://", oidc_settings())
    with TestClient(app) as client:
        seed_demo_users(app)
        app.state.token_validator = FakeValidator(
            {"non-member": AuthenticatedPrincipal(subject="not-a-member", tenant_id=TENANT_ID)}
        )
        for headers in (
            {},
            {"Authorization": "Bearer invalid"},
            {"Authorization": "Bearer non-member"},
        ):
            response = client.get("/v1/me", headers=headers)
            assert response.status_code == 403
            assert response.headers["content-type"].startswith("application/problem+json")
            assert response.json()["status"] == 403


def test_current_actor_is_declared_in_openapi() -> None:
    app = create_app("sqlite://")
    schema = app.openapi()
    response = schema["paths"]["/v1/me"]["get"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CurrentActorResponse"
    }
