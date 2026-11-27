from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.modules.attachments.application.attachment_service import (
    MalwareScannerUnavailableError,
    MalwareScanRejectedError,
)
from app.modules.attachments.infrastructure.filesystem_storage import LocalAttachmentStorage
from app.modules.attachments.persistence import Attachment
from app.modules.audit.persistence import AuditEvent
from app.modules.candidates.infrastructure.public_application import SqlAlchemyApplicationRepository
from app.modules.candidates.persistence import CandidateCase, CandidateConsent
from app.modules.notifications.persistence import OutboxEvent
from app.modules.organization.persistence import Membership
from app.modules.retention.infrastructure.sqlalchemy_repository import SqlAlchemyRetentionRepository
from app.modules.retention.persistence import RetentionPolicy
from app.shared.events import envelope
from app.shared.settings import Settings
from tests.integration.test_event_producers import validate
from tests.integration.test_tenant_rbac import bootstrap_tenant


@pytest.fixture
def careers(tmp_path):
    settings = Settings(
        app_env="test",
        attachment_storage_root=str(tmp_path),
        rate_limit_enabled=False,
        careers_apply_limit_per_hour=100,
        careers_apply_limit_per_email_per_day=100,
        cors_allowed_origins="http://localhost:3000",
    )
    app = create_app("sqlite://", settings)
    with TestClient(app) as client:
        tenant = bootstrap_tenant(client, "careers-demo", "admin")
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "admin"}
        job = client.post(
            "/v1/requisitions",
            headers=headers,
            json={"title": "Engineer", "department": "Engineering"},
        ).json()
        client.patch(
            f"/v1/requisitions/{job['id']}/publication", headers=headers, json={"published": True}
        )
        yield app, client, tenant, headers, job, tmp_path


def apply(careers, fields=None, file=None, url=None, headers=None):
    _, client, tenant, _, job, _ = careers
    return client.post(
        url or f"/v1/public/tenants/{tenant['slug']}/requisitions/{job['id']}/applications",
        data={
            **{
                "first_name": "Avery",
                "last_name": "Example",
                "email": "avery@example.test",
                "consent_version": "careers-v1",
                "consent_accepted": "true",
                "website": "",
            },
            **(fields or {}),
        },
        files={"cv": file or ("resume.pdf", b"%PDF-1.7\nclean", "application/pdf")},
        headers=headers or {},
    )


def counts(careers):
    app, _, _, _, _, root = careers
    with app.state.session_factory() as session:
        return [
            session.scalar(select(func.count()).select_from(t))
            for t in (CandidateCase, CandidateConsent, Attachment)
        ] + [len(list(root.iterdir()))]


def _outbox_events(careers):
    app, _, tenant, *_ = careers
    with app.state.session_factory() as session:
        return list(
            session.scalars(select(OutboxEvent).where(OutboxEvent.tenant_id == tenant["id"]))
        )


@pytest.mark.parametrize("correlation", ["careers.trace_123", "forged <script>"])
def test_application_emits_one_catalog_valid_creation_event(careers, correlation):
    app, _, tenant, _, job, _ = careers
    response = apply(careers, headers={"X-Correlation-Id": correlation})
    assert response.status_code == 202
    events = _outbox_events(careers)
    assert len(events) == 1
    event = events[0]
    with app.state.session_factory() as session:
        candidate = session.scalar(
            select(CandidateCase).where(CandidateCase.tenant_id == tenant["id"])
        )
        candidate_id = candidate.id
    assert event.topic == "candidate_case.created.v1"
    assert event.status == "pending"
    assert event.subject == candidate_id
    assert event.actor_id == "system:careers"
    assert event.correlation_id == response.headers["x-correlation-id"]
    assert event.payload_json == {
        "candidate_case_id": candidate_id,
        "requisition_id": job["id"],
        "stage": "applied",
        "channel": "careers_site",
        "version": 1,
    }
    message = envelope(event)
    validate(message)
    assert message["actorid"] == "system:careers"
    assert message["tenantid"] == tenant["id"]
    assert (
        message["correlationid"] == message["causationid"] == response.headers["x-correlation-id"]
    )


def test_apply_scan_create_consent_exact_and_reapply_immutable(careers):
    app, client, tenant, headers, job, _ = careers
    with app.state.session_factory() as session:
        session.add(RetentionPolicy(tenant_id=tenant["id"], retention_days=365))
        session.commit()
    consent = client.get("/v1/public/tenants/careers-demo/consent").json()
    with patch(
        "app.modules.attachments.infrastructure.filesystem_storage.NoopMalwareScanner.scan"
    ) as scanner:
        assert apply(careers, {"consent_text": "forged client consent"}).status_code == 202
        assert scanner.call_count == 1
        with app.state.session_factory() as session:
            record = session.scalar(select(CandidateCase))
            candidate_id = record.id
        detail = client.get(f"/v1/candidate-cases/{candidate_id}", headers=headers).json()
        assert detail["source"] == "careers"
        assert detail["consent"]["text"] == consent["text"]
        assert "365 days" in consent["text"]
        original_events = _outbox_events(careers)
        assert len(original_events) == 1
        assert apply(
            careers, {"email": "  AVERY@EXAMPLE.TEST ", "first_name": "Changed"}
        ).json() == {"status": "received"}
        assert scanner.call_count == 2
        assert [event.id for event in _outbox_events(careers)] == [
            event.id for event in original_events
        ]
        assert client.get(f"/v1/candidate-cases/{candidate_id}", headers=headers).json() == detail
    assert counts(careers) == [1, 1, 1, 1]
    with app.state.session_factory() as session:
        events = session.scalars(
            select(AuditEvent).where(AuditEvent.actor_id == "system:careers")
        ).all()
        assert {e.action for e in events} == {
            "candidate_case.created",
            "candidate_attachment.uploaded",
            "candidate_case.reapplied",
        }
        reapply = next(e for e in events if e.action.endswith("reapplied"))
        assert reapply.aggregate_id == candidate_id
        assert reapply.metadata_json == {"requisition_id": job["id"]}
        assert (
            session.scalar(select(Membership).where(Membership.user_id == "system:careers")) is None
        )


def test_honeypot_identical_success_no_scan_or_writes(careers):
    with patch(
        "app.modules.attachments.infrastructure.filesystem_storage.NoopMalwareScanner.scan"
    ) as scanner:
        result = apply(
            careers,
            {"website": "spam", "email": "", "consent_accepted": "false"},
            url="/v1/public/tenants/unknown/requisitions/unknown/applications",
        )
        assert result.status_code == 202 and result.json() == {"status": "received"}
        scanner.assert_not_called()
    assert counts(careers) == [0, 0, 0, 0]
    assert _outbox_events(careers) == []


@pytest.mark.parametrize(
    "fields",
    [
        {"first_name": ""},
        {"last_name": "x" * 101},
        {"first_name": "a\u202eb"},
        {"last_name": "a\x01b"},
        {"email": "invalid"},
        {"email": "x" * 321 + "@example.test"},
        {"consent_accepted": "false"},
        {"consent_version": "old"},
    ],
)
def test_fields_rejected_before_email_limit_and_scan(careers, fields):
    with (
        patch(
            "app.modules.candidates.infrastructure.public_application.RedisApplicationThrottle.consume_email"
        ) as throttle,
        patch(
            "app.modules.attachments.infrastructure.filesystem_storage.NoopMalwareScanner.scan"
        ) as scanner,
    ):
        assert apply(careers, fields).status_code == 422
        throttle.assert_not_called()
        scanner.assert_not_called()
    assert counts(careers) == [0, 0, 0, 0]
    assert _outbox_events(careers) == []


@pytest.mark.parametrize(
    "file",
    [
        ("bad.pdf", b"PK\x03\x04", "application/pdf"),
        (
            "bad.docx",
            b"%PDF-",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        ("bad.txt", b"%PDF-", "text/plain"),
        ("empty.pdf", b"", "application/pdf"),
        ("../bad.pdf", b"%PDF-", "application/pdf"),
    ],
)
def test_invalid_files_no_scan_or_persistence(careers, file):
    with patch(
        "app.modules.attachments.infrastructure.filesystem_storage.NoopMalwareScanner.scan"
    ) as scanner:
        assert apply(careers, file=file).status_code == 422
        scanner.assert_not_called()
    assert counts(careers) == [0, 0, 0, 0]
    assert _outbox_events(careers) == []


@pytest.mark.parametrize(
    "error,status", [(MalwareScanRejectedError(), 422), (MalwareScannerUnavailableError(), 503)]
)
def test_scanner_failure_closed(careers, error, status):
    with patch(
        "app.modules.attachments.infrastructure.filesystem_storage.NoopMalwareScanner.scan",
        side_effect=error,
    ):
        response = apply(careers)
        assert response.status_code == status
        if status == 422:
            assert response.json()["detail"] == "file was rejected"
    assert counts(careers) == [0, 0, 0, 0]
    assert _outbox_events(careers) == []


def test_catalog_is_public_scoped_and_publication_reflected(careers):
    _, client, _, headers, job, _ = careers
    listing = client.get("/v1/public/tenants/careers-demo/requisitions").json()
    assert (
        listing["tenant"] == {"name": "Careers-Demo", "slug": "careers-demo"}
        or listing["tenant"]["slug"] == "careers-demo"
    )
    assert set(listing) == {"tenant", "upload_policy", "requisitions"}
    assert set(listing["requisitions"][0]) == {"id", "title", "department", "published_at"}
    assert listing["requisitions"][0]["id"] == job["id"]
    assert (
        "as long as needed" in client.get("/v1/public/tenants/careers-demo/consent").json()["text"]
    )
    client.patch(
        f"/v1/requisitions/{job['id']}/publication", headers=headers, json={"published": False}
    )
    assert client.get("/v1/public/tenants/careers-demo/requisitions").json()["requisitions"] == []
    assert apply(careers).status_code == 404
    assert (
        apply(
            careers, url=f"/v1/public/tenants/no-such-tenant/requisitions/{job['id']}/applications"
        ).status_code
        == 404
    )
    assert (
        apply(
            careers, url="/v1/public/tenants/careers-demo/requisitions/missing/applications"
        ).status_code
        == 404
    )
    assert client.get("/v1/public/tenants/missing/requisitions").status_code == 404
    assert client.get("/v1/public/tenants/missing/consent").status_code == 404
    assert counts(careers) == [0, 0, 0, 0]
    assert _outbox_events(careers) == []


@pytest.mark.parametrize(
    "headers,status",
    [
        ({"Transfer-Encoding": "chunked"}, 411),
        ({"Content-Length": "5308417"}, 413),
        ({"Content-Length": "bogus"}, 411),
        ({"Origin": "https://attacker.test"}, 403),
    ],
)
def test_framing_and_origin_precede_parsing(careers, headers, status):
    with patch("starlette.requests.Request.form", side_effect=AssertionError("parsed")):
        assert apply(careers, headers=headers).status_code == status


def test_missing_length_before_parsing(careers):
    _, client, tenant, _, job, _ = careers
    request = client.build_request(
        "POST",
        f"/v1/public/tenants/{tenant['slug']}/requisitions/{job['id']}/applications",
        content=b"x",
    )
    del request.headers["content-length"]
    assert client.send(request).status_code == 411


@pytest.mark.parametrize("which", ["ip", "email"])
def test_redis_outage_returns_503(careers, which):
    app, *_ = careers
    limiter = app.state.rate_limiter
    original = limiter.consume

    def consume(key, **kwargs):
        if f":{which}:" in key:
            raise ConnectionError("down")
        return original(key, **kwargs)

    with patch.object(limiter, "consume", side_effect=consume):
        assert apply(careers).status_code == 503
    assert counts(careers) == [0, 0, 0, 0]
    assert _outbox_events(careers) == []


def test_email_keys_hashed_and_quotas_order(careers):
    app, *_ = careers
    app.state.runtime_settings.careers_apply_limit_per_email_per_day = 3
    keys = []
    original = app.state.rate_limiter.consume

    def consume(key, **kwargs):
        keys.append(key)
        return original(key, **kwargs)

    with patch.object(app.state.rate_limiter, "consume", side_effect=consume):
        for _ in range(3):
            assert (
                apply(careers, file=("bad.pdf", b"invalid", "application/pdf")).status_code == 422
            )
        response = apply(careers, {"email": "AVERY@EXAMPLE.TEST"})
        assert response.status_code == 429 and int(response.headers["retry-after"]) > 0
    email_keys = [key for key in keys if ":email:" in key]
    assert len(set(email_keys)) == 1 and len(email_keys[0].split(":")[-1]) == 64
    assert all("avery" not in key for key in keys)


def test_ip_limit_counts_honeypot_before_parsing(careers):
    app, *_ = careers
    app.state.runtime_settings.careers_apply_limit_per_hour = 5
    for _ in range(5):
        assert apply(careers, {"website": "bot"}).status_code == 202
    with patch("starlette.requests.Request.form", side_effect=AssertionError("parsed")):
        assert apply(careers).status_code == 429


def test_persistence_failure_compensates_object(careers):
    with (
        patch.object(
            SqlAlchemyApplicationRepository,
            "add_consent",
            side_effect=RuntimeError("persistence failed"),
        ),
        pytest.raises(RuntimeError),
    ):
        apply(careers)
    assert counts(careers) == [0, 0, 0, 0]
    assert _outbox_events(careers) == []


def test_system_principals_cannot_authenticate_even_with_membership(careers):
    app, client, tenant, headers, *_ = careers
    with app.state.session_factory() as session:
        session.add(
            Membership(tenant_id=tenant["id"], user_id="system:careers", role="tenant_admin")
        )
        session.commit()
    assert (
        client.get(
            "/v1/candidate-cases", headers={**headers, "X-Actor-Id": "system:careers"}
        ).status_code
        == 403
    )


def test_retention_clears_only_consent_text(careers):
    from datetime import UTC, datetime, timedelta

    app, _, tenant, *_ = careers
    assert apply(careers).status_code == 202
    with app.state.session_factory() as session:
        record = session.scalar(select(CandidateCase))
        record.stage = "rejected"
        record.terminal_at = datetime.now(UTC) - timedelta(days=366)
        session.add(RetentionPolicy(tenant_id=tenant["id"], retention_days=365))
        session.commit()
        before = session.get(CandidateConsent, record.id)
        version, accepted = before.version, before.accepted_at
        repo = SqlAlchemyRetentionRepository(
            session, attachment_storage=LocalAttachmentStorage(str(careers[-1]))
        )
        assert repo.purge_due(tenant_id=tenant["id"], now=datetime.now(UTC)) == [record.id]
        session.commit()
        assert before.text is None and (before.version, before.accepted_at) == (version, accepted)
        assert repo.purge_due(tenant_id=tenant["id"], now=datetime.now(UTC)) == []


def test_metrics_only_outcome_labels():
    from app.shared.observability import careers_applications

    assert careers_applications._labelnames == ("outcome",)


def test_api_counts_actual_body_and_file_size_boundaries(careers):
    app, *_ = careers
    app.state.runtime_settings.attachment_max_bytes = 16
    assert (
        apply(careers, file=("cv.pdf", b"%PDF-" + b"x" * 11, "application/pdf")).status_code == 202
    )
    assert (
        apply(careers, file=("cv.pdf", b"%PDF-" + b"x" * 12, "application/pdf")).status_code == 422
    )
    assert (
        apply(
            careers,
            file=("cv.pdf", b"%PDF-" + b"x" * 65548, "application/pdf"),
            headers={"content-length": "100"},
        ).status_code
        == 413
    )


def test_listing_orders_caps_and_does_not_expose_other_tenants(careers):
    from datetime import UTC, datetime, timedelta

    from app.modules.organization.persistence import Requisition

    app, client, tenant, _, _, _ = careers
    other = bootstrap_tenant(client, "other-demo", "other-admin")
    with app.state.session_factory() as session:
        for i in range(105):
            session.add(
                Requisition(
                    id=f"public-{i:03}",
                    tenant_id=tenant["id"],
                    title=f"Role {i}",
                    department="Demo",
                    created_by="admin",
                    published=True,
                    published_at=datetime.now(UTC) + timedelta(days=i),
                )
            )
        session.add(
            Requisition(
                id="foreign-job",
                tenant_id=other["id"],
                title="Foreign",
                department="Demo",
                created_by="other-admin",
                published=True,
                published_at=datetime.now(UTC),
            )
        )
        session.commit()
    listing = client.get("/v1/public/tenants/careers-demo/requisitions").json()["requisitions"]
    assert (
        len(listing) == 100
        and listing[0]["id"] == "public-104"
        and listing[-1]["id"] == "public-005"
    )
    assert (
        apply(
            careers, url="/v1/public/tenants/careers-demo/requisitions/foreign-job/applications"
        ).status_code
        == 404
    )


def test_system_subject_token_rejected(careers):
    from unittest.mock import Mock

    from app.modules.identity.application.authentication import AuthenticatedPrincipal

    app, client, tenant, _, _, _ = careers
    app.state.auth_mode = "oidc_jwt"
    # Even a valid, signed principal is forbidden before membership resolution.
    app.state.token_validator = Mock()
    app.state.token_validator.validate.return_value = AuthenticatedPrincipal(
        subject="system:careers", tenant_id=tenant["id"]
    )
    assert (
        client.get(
            "/v1/candidate-cases", headers={"Authorization": "Bearer test-token"}
        ).status_code
        == 403
    )


@pytest.mark.parametrize("admin_id", ["system:careers", "system:future-worker"])
def test_bootstrap_cannot_assign_system_membership(careers, admin_id):
    from app.modules.organization.persistence import Tenant

    app, client, *_ = careers
    result = client.post(
        "/v1/tenants",
        json={
            "name": "Invalid Bootstrap",
            "slug": "invalid-system-bootstrap",
            "admin_id": admin_id,
        },
    )
    assert result.status_code == 422
    with app.state.session_factory() as session:
        assert (
            session.scalar(select(Tenant).where(Tenant.slug == "invalid-system-bootstrap")) is None
        )
        assert session.scalar(select(Membership).where(Membership.user_id == admin_id)) is None
