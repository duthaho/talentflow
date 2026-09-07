from __future__ import annotations

import json
from dataclasses import dataclass
from time import monotonic
from urllib.request import urlopen

import jwt

from app.modules.identity.application.authentication import (
    AuthenticatedPrincipal,
    AuthenticationError,
)


class JwksProvider:
    def get(self) -> dict:  # noqa: ANN201
        raise NotImplementedError


@dataclass
class HttpJwksProvider(JwksProvider):
    url: str
    cache_ttl_seconds: int
    _cached: dict | None = None
    _expires_at: float = 0

    def get(self) -> dict:  # noqa: ANN201
        if self._cached is None or monotonic() >= self._expires_at:
            with urlopen(self.url, timeout=5) as response:  # noqa: S310
                self._cached = json.load(response)
            self._expires_at = monotonic() + self.cache_ttl_seconds
        return self._cached

    def refresh(self) -> dict:  # noqa: ANN201
        self._cached = None
        return self.get()


@dataclass
class JwtValidator:
    issuer: str
    audience: str
    algorithms: tuple[str, ...]
    jwks: JwksProvider

    def validate(self, token: str) -> AuthenticatedPrincipal:
        try:
            header = jwt.get_unverified_header(token)
            key = self._key_for(header.get("kid"), refresh=False)
            try:
                claims = jwt.decode(
                    token,
                    key=key,
                    algorithms=list(self.algorithms),
                    audience=self.audience,
                    issuer=self.issuer,
                    options={"require": ["exp", "sub", "tenant_id"]},
                )
            except jwt.InvalidSignatureError:
                raise
        except jwt.InvalidSignatureError:
            raise AuthenticationError("Invalid bearer token") from None
        except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
            raise AuthenticationError("Invalid bearer token") from None
        tenant_id = claims.get("tenant_id")
        if not isinstance(tenant_id, str) or not tenant_id:
            raise AuthenticationError("Invalid bearer token")
        return AuthenticatedPrincipal(subject=claims["sub"], tenant_id=tenant_id)

    def _key_for(self, key_id: str | None, *, refresh: bool) -> object:
        document = (
            self.jwks.refresh() if refresh and hasattr(self.jwks, "refresh") else self.jwks.get()
        )
        for jwk in document.get("keys", []):
            if jwk.get("kid") == key_id:
                return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        if not refresh and hasattr(self.jwks, "refresh"):
            return self._key_for(key_id, refresh=True)
        raise KeyError(key_id)
