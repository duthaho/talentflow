"""Standard Webhooks signing; receivers verify bytes before parsing JSON."""

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Protocol


class WebhookSecretCipher(Protocol):
    def encrypt(self, plaintext: bytes, aad: bytes) -> str: ...
    def decrypt(self, ciphertext: str, aad: bytes) -> bytes: ...


@dataclass(frozen=True)
class SigningKey:
    value: bytes = field(repr=False)

    def __str__(self):
        return "[REDACTED]"


def signature(key: bytes, event_id: str, timestamp: str, body: bytes) -> str:
    signed = f"{event_id}.{timestamp}.".encode() + body
    return "v1," + base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()


class InvalidWebhook(ValueError):
    pass


def verify(secret: str, headers, body: bytes, now: float | None = None) -> None:
    event_id = headers.get("webhook-id")
    timestamp = headers.get("webhook-timestamp")
    signatures = headers.get("webhook-signature")
    try:
        if not event_id or not timestamp or not signatures:
            raise ValueError
        if not (timestamp.isascii() and timestamp.isdigit()) or len(timestamp) > 12:
            raise ValueError
        if abs((time.time() if now is None else now) - int(timestamp)) > 300:
            raise ValueError
        if not secret.startswith("whsec_"):
            raise ValueError
        key = base64.b64decode(secret[6:], validate=True)
        if len(key) != 32:
            raise ValueError
        expected = signature(key, event_id, timestamp, body)
        if any(hmac.compare_digest(entry, expected) for entry in signatures.split()):
            return
    except (ValueError, TypeError, AttributeError, UnicodeError):
        pass
    raise InvalidWebhook("Invalid signature or timestamp")


def aad(tenant_id: str, endpoint_id: str, secret_id: str) -> bytes:
    return f"webhook-secret:{tenant_id}:{endpoint_id}:{secret_id}".encode()
