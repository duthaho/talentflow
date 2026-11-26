import hashlib
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import Request, Response
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.api.idempotency import Replay, _complete, fingerprint
from app.shared.database import Base, build_session_factory
from app.shared.idempotency import IdempotencyRecord, purge_expired_keys
from app.shared.settings import Settings
from app.workers.retention import ScheduledRetentionCycle


@pytest.mark.parametrize("value", [0, -1])
def test_ttl_must_be_positive(value):
    with pytest.raises(ValidationError):
        Settings(idempotency_key_ttl_seconds=value)
    assert Settings().idempotency_key_ttl_seconds == 86400


def test_fingerprint_includes_target_and_canonical_unicode_json():
    class Route:
        path_format = "/v1/offers/{offer_id}/approvals"

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "route": Route(),
            "path_params": {"offer_id": "one"},
            "headers": [],
        }
    )
    first = fingerprint(request, {"b": "Đ", "a": 1})
    assert first == fingerprint(request, {"a": 1, "b": "Đ"})
    request.scope["path_params"] = {"offer_id": "two"}
    assert first != fingerprint(request, {"a": 1, "b": "Đ"})


def test_conditional_fingerprints_preserve_legacy_keys_and_include_header():
    class Route:
        path_format = "/v1/offers/{offer_id}/approvals"

    body = {"decision": "approved", "expected_version": 1}
    scope = {
        "type": "http",
        "method": "POST",
        "route": Route(),
        "path_params": {"offer_id": "one"},
        "headers": [],
    }
    legacy = hashlib.sha256(
        json.dumps(
            ["POST", Route.path_format, {"offer_id": "one"}, body],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    assert fingerprint(Request(scope), body) == legacy
    matching = fingerprint(Request({**scope, "headers": [(b"if-match", b'"1"')]}), body)
    stale = fingerprint(Request({**scope, "headers": [(b"if-match", b'"2"')]}), body)
    assert len({legacy, matching, stale}) == 3

    class UnversionedRoute:
        path_format = "/v1/requisitions"

    scope["route"] = UnversionedRoute()
    assert fingerprint(Request(scope), body) == fingerprint(
        Request({**scope, "headers": [(b"if-match", b"ignored")]}), body
    )


def test_expiry_cleanup_is_bounded_and_preserves_live_rows():
    engine = create_engine("sqlite://")
    IdempotencyRecord.__table__.create(engine)
    now = datetime.now(UTC)
    with Session(engine) as session:
        for index in range(4):
            session.add(
                IdempotencyRecord(
                    id=str(index),
                    tenant_id="tenant",
                    actor_id="actor",
                    key=str(index),
                    fingerprint="a" * 64,
                    state="in_progress",
                    expires_at=now + timedelta(days=1 if index == 3 else -1),
                )
            )
        session.commit()
        assert purge_expired_keys(session, batch_size=2) == 2
        assert session.query(IdempotencyRecord).count() == 2
        assert purge_expired_keys(session, batch_size=2) == 1
        assert purge_expired_keys(session, batch_size=2) == 0
        assert session.query(IdempotencyRecord).one().id == "3"
    engine.dispose()


def test_response_storage_allowlists_headers():
    engine = create_engine("sqlite://")
    IdempotencyRecord.__table__.create(engine)
    with Session(engine) as session:
        session.add(
            IdempotencyRecord(
                id="row",
                tenant_id="tenant",
                actor_id="actor",
                key="key",
                fingerprint="a" * 64,
                state="in_progress",
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        session.commit()
        _complete(
            session,
            "row",
            Response(
                content='{"ok":true}',
                status_code=201,
                headers={
                    "Content-Type": "application/json",
                    "Location": "/v1/example",
                    "ETag": '"3"',
                    "Set-Cookie": "secret",
                    "Authorization": "secret",
                },
            ),
        )
        record = session.get(IdempotencyRecord, "row")
        assert record.headers == {
            "content-type": "application/json",
            "location": "/v1/example",
            "etag": '"3"',
        }
        replay = Replay(record).response
        assert replay.status_code == 201
        assert replay.headers["Location"] == "/v1/example"
        assert replay.headers["ETag"] == '"3"'
        assert "Set-Cookie" not in replay.headers
    engine.dispose()


def test_scheduled_retention_purges_keys_without_tenant_policies(tmp_path):
    sessions = build_session_factory(f"sqlite:///{tmp_path / 'cleanup.db'}")
    Base.metadata.create_all(sessions.kw["bind"])
    with sessions() as session:
        session.add(
            IdempotencyRecord(
                id="expired",
                tenant_id="tenant",
                actor_id="actor",
                key="key",
                fingerprint="a" * 64,
                state="completed",
                expires_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        session.commit()
    cycle = ScheduledRetentionCycle(
        sessions, schedule_seconds=60, batch_size=100, storage=str(tmp_path)
    )
    assert cycle() == 0
    with sessions() as session:
        assert session.query(IdempotencyRecord).count() == 0
    sessions.kw["bind"].dispose()


def test_expand_migration_upgrade_and_downgrade():
    path = Path(__file__).parents[2] / "migrations/versions/d60a001_add_idempotency_records.py"
    spec = importlib.util.spec_from_file_location("idempotency_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            indexes = {
                item["name"]: item
                for item in inspect(connection).get_indexes("idempotency_records")
            }
            assert indexes["uq_idempotency_scope_key"]["unique"]
            assert indexes["ix_idempotency_expires_at"]["column_names"] == ["expires_at"]
            migration.downgrade()
            assert "idempotency_records" not in inspect(connection).get_table_names()
    engine.dispose()
