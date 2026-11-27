"""Opt-in real clamd, Redis and PostgreSQL evidence on disposable services."""

import io
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.modules.attachments.persistence import Attachment
from app.modules.audit.persistence import AuditEvent
from app.modules.candidates.infrastructure.public_application import SqlAlchemyApplicationRepository
from app.modules.candidates.persistence import CandidateCase, CandidateConsent
from app.shared.rate_limit import RedisFixedWindowRateLimiter
from app.shared.settings import Settings
from tests.integration.test_public_careers import apply
from tests.integration.test_tenant_rbac import bootstrap_tenant


def docx(content):
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr("word/document.xml", content)
    return buffer.getvalue()


@pytest.mark.skipif(not os.getenv("CAREERS_CLAMD_PORT"), reason="Requires real clamd")
def test_real_clamd_clean_pdf_docx_eicar_nested_bomb_and_down(tmp_path):
    app = create_app(
        "sqlite://",
        Settings(
            app_env="test",
            attachment_storage_root=str(tmp_path),
            attachment_scan_mode="clamav",
            attachment_clamav_host="127.0.0.1",
            attachment_clamav_port=int(os.environ["CAREERS_CLAMD_PORT"]),
            rate_limit_enabled=False,
            careers_apply_limit_per_hour=100,
            careers_apply_limit_per_email_per_day=100,
        ),
    )
    with TestClient(app) as client:
        tenant = bootstrap_tenant(client, "careers-demo", "live-admin")
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "live-admin"}
        job = client.post(
            "/v1/requisitions", headers=headers, json={"title": "Engineer", "department": "Demo"}
        ).json()
        client.patch(
            f"/v1/requisitions/{job['id']}/publication", headers=headers, json={"published": True}
        )
        context = (app, client, tenant, headers, job, tmp_path)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        assert apply(context).status_code == 202
        assert (
            apply(
                context,
                {"email": "docx@example.test"},
                file=("clean.docx", docx("<document>Clean CV</document>"), mime),
            ).status_code
            == 202
        )
        eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
        assert (
            apply(
                context, {"email": "eicar@example.test"}, file=("infected.docx", docx(eicar), mime)
            ).status_code
            == 422
        )
        nested = docx("payload")
        for _ in range(12):
            nested = docx(nested)
        assert (
            apply(
                context, {"email": "bomb@example.test"}, file=("nested.docx", nested, mime)
            ).status_code
            == 422
        )
        app.state.runtime_settings.attachment_clamav_port = 1
        assert apply(context, {"email": "down@example.test"}).status_code == 503
        with app.state.session_factory() as session:
            for model in (CandidateCase, CandidateConsent, Attachment):
                assert session.scalar(select(func.count()).select_from(model)) == 2
        assert len(list(tmp_path.iterdir())) == 2


@pytest.mark.skipif(
    not os.getenv("CAREERS_TEST_DATABASE_URL"), reason="Requires disposable PostgreSQL"
)
def test_postgres_synchronized_apply_race_one_case_no_orphan(tmp_path):
    app = create_app(
        os.environ["CAREERS_TEST_DATABASE_URL"],
        Settings(
            app_env="test",
            attachment_storage_root=str(tmp_path),
            rate_limit_enabled=False,
            careers_apply_limit_per_hour=100,
            careers_apply_limit_per_email_per_day=100,
        ),
    )
    with TestClient(app) as client:
        actor_id = "race-admin-" + uuid4().hex
        tenant = bootstrap_tenant(client, "race-" + uuid4().hex, actor_id)
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": actor_id}
        job = client.post(
            "/v1/requisitions", headers=headers, json={"title": "Engineer", "department": "Demo"}
        ).json()
        client.patch(
            f"/v1/requisitions/{job['id']}/publication", headers=headers, json={"published": True}
        )
        context = (app, client, tenant, headers, job, tmp_path)
        barrier = Barrier(2)
        original = SqlAlchemyApplicationRepository.find_id_by_email

        def synchronized(self, tenant_id, email):
            result = original(self, tenant_id, email)
            if result is None:
                barrier.wait(timeout=20)
            return result

        with (
            patch.object(SqlAlchemyApplicationRepository, "find_id_by_email", synchronized),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            results = list(executor.map(lambda _: apply(context), range(2)))
        assert [(r.status_code, r.json()) for r in results] == [(202, {"status": "received"})] * 2
        with app.state.session_factory() as session:
            for model in (CandidateCase, CandidateConsent, Attachment):
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.tenant_id == tenant["id"])
                    )
                    == 1
                )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.action == "candidate_case.reapplied",
                        AuditEvent.tenant_id == tenant["id"],
                    )
                )
                == 1
            )
        assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.skipif(not os.getenv("CAREERS_TEST_REDIS_URL"), reason="Requires real Redis")
def test_real_redis_atomic_threshold_and_expiry():
    from uuid import uuid4

    limiter = RedisFixedWindowRateLimiter(os.environ["CAREERS_TEST_REDIS_URL"])
    key = "talentflow:careers:test:" + uuid4().hex
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            decisions = list(
                executor.map(
                    lambda _: limiter.consume(key, limit=5, window_seconds=3600), range(12)
                )
            )
        assert sum(d.allowed for d in decisions) == 5
        limiter._redis.expire(key, 0)
        assert limiter.consume(key, limit=5, window_seconds=3600).allowed
    finally:
        limiter._redis.delete(key)
        limiter.close()
