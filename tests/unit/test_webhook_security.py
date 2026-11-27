import asyncio
import base64
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.main import create_app
from app.modules.webhooks.application.signing import InvalidWebhook, SigningKey, signature, verify
from app.modules.webhooks.infrastructure.cipher import DEV_KEY, AesGcmCipher, parse_keyring
from app.modules.webhooks.infrastructure.egress import (
    EgressError,
    EgressGuard,
    PinnedSender,
    parse_allowlist,
)
from app.shared.settings import Settings

VECTOR_ID = "0b7e1c9a-4f3d-4c55-9a52-3f1f6f3c2d10"
VECTOR_BODY = b'{"specversion":"1.0","id":"0b7e1c9a-4f3d-4c55-9a52-3f1f6f3c2d10","source":"urn:talentflow:candidates","type":"candidate_case.stage_changed.v1","time":"2026-11-27T09:00:00Z","datacontenttype":"application/json","subject":"c-123","tenantid":"t-1","correlationid":"req-1","causationid":"req-1","data":{"candidate_case_id":"c-123","from_stage":"screening","to_stage":"interviewing","version":3}}'


def test_known_answer_and_replay_tamper_detection():
    sig = signature(bytes(range(32)), VECTOR_ID, "1795770000", VECTOR_BODY)
    assert sig == "v1,tf0j4MFE0WB8v3pV96njh8f00nDy2gSfd7KprE+McKU="
    headers = {"webhook-id": VECTOR_ID, "webhook-timestamp": "1795770000", "webhook-signature": sig}
    secret = "whsec_" + base64.b64encode(bytes(range(32))).decode()
    verify(secret, headers, VECTOR_BODY, now=1795770300)
    for body, now in [
        (VECTOR_BODY + b" ", 1795770000),
        (VECTOR_BODY, 1795770301),
        (VECTOR_BODY, 1795769699),
    ]:
        with pytest.raises(InvalidWebhook):
            verify(secret, headers, body, now=now)
    for timestamp in ("²", "-1", "bad", "9" * 100):
        with pytest.raises(InvalidWebhook):
            verify(secret, {**headers, "webhook-timestamp": timestamp}, VECTOR_BODY, now=1795770000)
    for bad in (
        {},
        {"webhook-id": VECTOR_ID},
        {"webhook-id": VECTOR_ID, "webhook-timestamp": "1795770000"},
    ):
        with pytest.raises(InvalidWebhook):
            verify(secret, bad, VECTOR_BODY, now=1795770000)
    assert str(SigningKey(b"sensitive")) == "[REDACTED]"
    assert "sensitive" not in repr(SigningKey(b"sensitive"))


def test_cipher_binds_tenant_endpoint_secret_and_supports_key_rotation():
    cipher = AesGcmCipher({"old": b"o" * 32, "new": b"n" * 32}, "new")
    first = cipher.encrypt(b"secret", b"tenant:endpoint:key")
    second = cipher.encrypt(b"secret", b"tenant:endpoint:key")
    assert first != second and first.startswith("tfgcm:v1:new:")
    assert cipher.decrypt(first, b"tenant:endpoint:key") == b"secret"
    for context in (b"other:endpoint:key", b"tenant:other:key", b"tenant:endpoint:other"):
        with pytest.raises(ValueError, match="decryption failed"):
            cipher.decrypt(first, context)
    with pytest.raises(ValueError):
        cipher.decrypt(first[:-4] + "AAAA", b"tenant:endpoint:key")
    old = AesGcmCipher({"old": b"o" * 32}, "old").encrypt(b"secret", b"aad")
    assert cipher.decrypt(old, b"aad") == b"secret"


@pytest.mark.parametrize(
    "address",
    [
        "::a9fe:a9fe",
        "::7f00:1",
        "fec0::1",
        "::ffff:169.254.169.254",
        "64:ff9b::a9fe:a9fe",
        "169.254.169.254",
        "fd00:ec2::254",
        "127.0.0.1",
        "::1",
        "224.0.0.1",
        "ff02::1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.0.1",
        "100.64.0.1",
        "0.0.0.0",
        "192.0.2.1",
        "2001:db8::1",
        "2002:7f00:1::1",
        "::ffff:127.0.0.1",
    ],
)
def test_blocked_resolver_addresses(address):
    async def resolver(host, port):
        return [address]

    guard = EgressGuard(resolver=resolver)
    with pytest.raises(EgressError, match="permitted"):
        asyncio.run(guard.check("https://receiver.example/hook"))


def test_mixed_records_blocked_and_literal_skips_dns():
    async def resolver(host, port):
        return ["93.184.216.34", "::1"]

    guard = EgressGuard(resolver=resolver)
    with pytest.raises(EgressError):
        asyncio.run(guard.check("https://receiver.example"))
    target = asyncio.run(guard.check("https://93.184.216.34"))
    assert target.ip == "93.184.216.34"


@pytest.mark.parametrize(
    "host",
    [
        "0x7f.1",
        "2130706433",
        "127.1",
        "0177.0.0.1",
        "123.456",
        "localhost",
        "evil.localhost",
        "app.internal",
        "app.local",
        "router.home.arpa",
        "[::a9fe:a9fe]",
    ],
)
def test_host_syntax_cannot_bypass_address_rules(host):
    async def resolver(host, port):
        return ["93.184.216.34"]

    with pytest.raises(EgressError):
        asyncio.run(EgressGuard(resolver=resolver).check("https://" + host))


@pytest.mark.parametrize(
    "network",
    [
        "127.0.0.0/8",
        "0.0.0.0/0",
        "169.254.0.0/16",
        "::/0",
        "::/96",
        "fec0::/10",
        "fe80::/10",
        "fd00:ec2::254/128",
        "::ffff:0:0/96",
    ],
)
def test_allowlist_cannot_authorize_metadata_loopback_or_tunnels(network):
    with pytest.raises(ValueError):
        parse_allowlist(network)


def test_demo_allowlist_http_port_idn_and_resolution_errors():
    calls = []

    async def resolver(host, port):
        calls.append(host)
        return ["172.29.62.5"]

    guard = EgressGuard(
        allow_http=True, allowlist=parse_allowlist("172.29.62.0/24"), resolver=resolver
    )
    target = asyncio.run(guard.check("http://bücher.example:9000/hook"))
    assert target.host == "xn--bcher-kva.example"
    assert target.port == 9000 and calls == ["xn--bcher-kva.example"]

    async def failed(host, port):
        raise OSError("secret address")

    with pytest.raises(EgressError, match="resolution failed"):
        asyncio.run(EgressGuard(resolver=failed).check("https://receiver.example"))


@pytest.mark.parametrize(
    "value,active",
    [
        ("", "dev"),
        ("dev:bad", "dev"),
        (
            "same:"
            + base64.b64encode(b"x" * 32).decode()
            + ",same:"
            + base64.b64encode(b"y" * 32).decode(),
            "same",
        ),
        ("test:" + base64.b64encode(b"x" * 32).decode(), "missing"),
    ],
)
def test_bad_keyrings(value, active):
    with pytest.raises(ValueError):
        parse_keyring(value, active)


def production(**changes):
    return Settings(
        app_env="production",
        auth_mode="oidc_jwt",
        database_url="postgresql+psycopg://test@db/db",
        cors_allowed_origins="https://console.example",
        oidc_issuer="https://issuer.example",
        oidc_audience="api",
        oidc_jwks_url="https://issuer.example/keys",
        redis_url="redis://redis:6379/0",
        attachment_scan_mode="clamav",
        attachment_storage_root="/app/data",
        calendar_public_base_url="https://console.example",
        webhook_secret_active_key_id=changes.pop("webhook_secret_active_key_id", "key"),
        webhook_secret_keys=changes.pop(
            "webhook_secret_keys", "key:" + base64.b64encode(b"x" * 32).decode()
        ),
        **changes,
    )


def test_production_rejects_dev_key_bytes_even_renamed_and_egress_exceptions():
    assert production().app_env == "production"
    for config in [
        dict(webhook_allow_http=True),
        dict(webhook_private_network_allowlist="172.29.62.0/24"),
        dict(
            webhook_secret_keys="renamed:" + base64.b64encode(DEV_KEY).decode(),
            webhook_secret_active_key_id="renamed",
        ),
        dict(
            webhook_secret_keys="dev:" + base64.b64encode(b"z" * 32).decode(),
            webhook_secret_active_key_id="dev",
        ),
    ]:
        with pytest.raises(ValidationError):
            production(**config)


def test_openapi_paths_and_schemas_match_approved_contract():
    approved = yaml.safe_load(Path("docs/webhooks/openapi.yaml").read_text())
    generated = create_app().openapi()
    for path, operations in approved["paths"].items():
        actual = generated["paths"][path]
        for method, operation in operations.items():
            assert actual[method] == (
                {**operation, "security": [{"bearerAuth": []}]}
                if method != "parameters"
                else operation
            )
    for name, schema in approved["components"]["schemas"].items():
        assert generated["components"]["schemas"][name] == schema
    assert generated["webhooks"] == approved["webhooks"]


def test_transport_pins_ip_preserves_host_and_tls_name(monkeypatch):
    observed = {}

    class Writer:
        from types import SimpleNamespace

        transport = SimpleNamespace(abort=lambda: None)

        def write(self, data):
            observed["wire"] = data

        async def drain(self):
            pass

        def close(self):
            observed["closed"] = True

    class Reader:
        async def readuntil(self, sep):
            return b"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1/\r\n\r\n"

        async def read(self, size):
            return b""

    async def connect(host, port, **options):
        observed.update(host=host, port=port, options=options)
        return Reader(), Writer()

    calls = []

    async def resolver(host, port):
        calls.append(host)
        return ["93.184.216.34"]

    monkeypatch.setattr(asyncio, "open_connection", connect)
    result = asyncio.run(
        PinnedSender(EgressGuard(resolver=resolver)).send(
            "https://receiver.example/hook?token=hidden", {"webhook-id": "id"}, b"{}"
        )
    )
    assert result.status_code == 302 and result.error_code == "redirect"
    assert observed["host"] == "93.184.216.34"
    assert observed["options"]["server_hostname"] == "receiver.example"
    assert observed["options"]["ssl"].check_hostname
    assert b"Host: receiver.example\r\n" in observed["wire"]
    assert b"Authorization:" not in observed["wire"] and b"Cookie:" not in observed["wire"]
    assert calls == ["receiver.example"] and observed["closed"]


def test_async_dns_checks_both_families_and_fails_closed(monkeypatch):
    from types import SimpleNamespace

    import dns.asyncresolver
    import dns.resolver

    from app.modules.webhooks.infrastructure.egress import resolve

    calls = []

    class Resolver:
        async def resolve(self, host, kind, **options):
            calls.append((host, kind, options))
            if kind == "AAAA":
                raise dns.resolver.NoAnswer
            return [SimpleNamespace(address="93.184.216.34")]

    monkeypatch.setattr(dns.asyncresolver, "Resolver", Resolver)
    assert asyncio.run(resolve("receiver.example", 443)) == ["93.184.216.34"]
    assert {call[1] for call in calls} == {"A", "AAAA"}
    assert all(call[2]["lifetime"] == 2 and not call[2]["search"] for call in calls)

    class Failed:
        async def resolve(self, *args, **kwargs):
            raise dns.resolver.NXDOMAIN

    monkeypatch.setattr(dns.asyncresolver, "Resolver", Failed)
    with pytest.raises(OSError):
        asyncio.run(resolve("receiver.example", 443))


def test_catalog_matches_runtime_subscriptions():
    from app.modules.webhooks.application.contracts import EVENT_TYPES

    catalog = yaml.safe_load(Path("docs/events/asyncapi.yaml").read_text())
    public = {
        message["name"]: message["x-talentflow"]["status"]
        for message in catalog["components"]["messages"].values()
        if message["x-talentflow"]["webhook"]
    }
    assert {name: metadata[0] for name, metadata in EVENT_TYPES.items()} == public
