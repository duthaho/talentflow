from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.identity.application.authentication import AuthenticatedPrincipal
from app.shared.settings import Settings


class FakeValidator:
    def validate(self, token: str) -> AuthenticatedPrincipal:
        if token != "valid-token":
            from app.modules.identity.application.authentication import AuthenticationError

            raise AuthenticationError("Invalid bearer token")
        return AuthenticatedPrincipal(subject="admin", tenant_id=self.tenant_id)


def test_oidc_mode_uses_bearer_claims_not_development_headers() -> None:
    settings = Settings(
        auth_mode="oidc_jwt",
        oidc_issuer="https://issuer.example",
        oidc_audience="talentflow",
        oidc_jwks_url="https://issuer.example/jwks",
    )
    app = create_app("sqlite://", settings)
    with TestClient(app) as client:
        tenant = client.post(
            "/v1/tenants", json={"name": "Acme", "slug": "acme", "admin_id": "admin"}
        ).json()
        app.state.token_validator = FakeValidator()
        app.state.token_validator.tenant_id = tenant["id"]
        response = client.post(
            "/v1/requisitions",
            headers={
                "Authorization": "Bearer valid-token",
                "X-Tenant-Id": "wrong",
                "X-Actor-Id": "wrong",
            },
            json={"title": "Engineer", "department": "Engineering"},
        )
    assert response.status_code == 201
