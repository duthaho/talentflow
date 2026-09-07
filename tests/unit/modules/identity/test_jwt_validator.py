from datetime import UTC, datetime, timedelta
from json import loads

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from app.modules.identity.infrastructure.jwt_validator import JwtValidator


class StaticJwks:
    def __init__(self, document: dict):
        self.document = document

    def get(self) -> dict:
        return self.document


def test_jwt_validator_verifies_signature_issuer_audience_and_tenant_claim() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk["kid"] = "key-1"
    token = jwt.encode(
        {
            "sub": "actor-1",
            "tenant_id": "tenant-1",
            "iss": "https://issuer.example",
            "aud": "talentflow",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "key-1"},
    )
    principal = JwtValidator(
        issuer="https://issuer.example",
        audience="talentflow",
        algorithms=("RS256",),
        jwks=StaticJwks({"keys": [public_jwk]}),
    ).validate(token)
    assert principal.subject == "actor-1"
    assert principal.tenant_id == "tenant-1"
