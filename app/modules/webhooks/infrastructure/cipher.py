import base64
import re
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Public local-development fixture, never a production key.
DEV_KEY = bytes(range(32))
DEV_KEYRING = "dev:" + base64.b64encode(DEV_KEY).decode()


def parse_keyring(value: str, active: str, *, production: bool = False) -> dict[str, bytes]:
    keys = {}
    try:
        for entry in value.split(","):
            kid, encoded = entry.split(":", 1)
            key = base64.b64decode(encoded, validate=True)
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", kid) or kid in keys or len(key) != 32:
                raise ValueError
            if production and (kid == "dev" or key == DEV_KEY):
                raise ValueError
            keys[kid] = key
        if active not in keys:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("Invalid webhook encryption keyring configuration") from None
    return keys


class AesGcmCipher:
    def __init__(self, keys: dict[str, bytes], active: str):
        self._keys = keys
        self.active = active

    def encrypt(self, plaintext: bytes, aad: bytes) -> str:
        nonce = secrets.token_bytes(12)
        encrypted = AESGCM(self._keys[self.active]).encrypt(nonce, plaintext, aad)
        return f"tfgcm:v1:{self.active}:" + base64.b64encode(nonce + encrypted).decode()

    def decrypt(self, ciphertext: str, aad: bytes) -> bytes:
        try:
            prefix, version, kid, encoded = ciphertext.split(":", 3)
            if prefix != "tfgcm" or version != "v1":
                raise ValueError
            raw = base64.b64decode(encoded, validate=True)
            return AESGCM(self._keys[kid]).decrypt(raw[:12], raw[12:], aad)
        except Exception:
            raise ValueError("Webhook secret decryption failed") from None


def build_cipher(settings) -> AesGcmCipher:
    return AesGcmCipher(
        parse_keyring(
            settings.webhook_secret_keys.get_secret_value(),
            settings.webhook_secret_active_key_id,
            production=settings.app_env == "production",
        ),
        settings.webhook_secret_active_key_id,
    )
