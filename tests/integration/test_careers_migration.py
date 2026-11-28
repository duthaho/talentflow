import os

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.shared.system_users import ensure_system_users


@pytest.mark.parametrize(
    "database_url",
    [
        pytest.param(None, id="sqlite"),
        pytest.param(
            os.getenv("CAREERS_MIGRATION_DATABASE_URL"),
            id="postgres",
            marks=pytest.mark.skipif(
                not os.getenv("CAREERS_MIGRATION_DATABASE_URL"),
                reason="Requires disposable migration PostgreSQL",
            ),
        ),
    ],
)
def test_expand_source_default_consent_nullable_and_downgrade_keeps_system_user(
    tmp_path, monkeypatch, database_url
):
    url = database_url or f"sqlite:///{tmp_path / 'careers.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config()
    config.set_main_option("script_location", "migrations")
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["d65a001"]
    assert script.get_revision("d65a001").down_revision == "d127a001"
    assert script.get_revision("d127a001").down_revision == "d62a001"
    command.upgrade(config, "d62a001")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tenants (id,name,slug,created_at) VALUES ('t','Demo','demo',CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text("INSERT INTO users (id,created_at) VALUES ('admin',CURRENT_TIMESTAMP)")
        )
        connection.execute(
            text(
                "INSERT INTO requisitions (id,tenant_id,title,department,created_by,created_at) VALUES ('job','t','Engineer','Demo','admin',CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO candidate_cases (id,tenant_id,requisition_id,first_name,last_name,email,stage,version,created_by,created_at) VALUES ('c','t','job','Demo','Candidate','demo@example.test','applied',1,'admin',CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO webhook_endpoints (id,tenant_id,url,status,created_by,created_at,updated_at) VALUES ('existing-webhook','t','https://receiver.example/hook','enabled','admin',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
    command.upgrade(config, "head")
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT source FROM candidate_cases WHERE id='c'")) == "staff"
        connection.execute(
            text(
                "INSERT INTO candidate_consents (candidate_case_id,tenant_id,version,text,accepted_at) VALUES ('c','t','careers-v1',NULL,CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "UPDATE candidate_cases SET source='careers',created_by='system:careers' WHERE id='c'"
            )
        )
    with Session(engine) as session:
        ensure_system_users(session)
        ensure_system_users(session)
    command.downgrade(config, "d62a001")
    assert not inspect(engine).has_table("candidate_consents")
    assert inspect(engine).has_table("webhook_endpoints")
    assert inspect(engine).has_table("webhook_deliveries")
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT url FROM webhook_endpoints WHERE id='existing-webhook'"))
            == "https://receiver.example/hook"
        )
        assert connection.scalar(text("SELECT count(*) FROM users WHERE id='system:careers'")) == 1
        assert (
            connection.scalar(text("SELECT created_by FROM candidate_cases WHERE id='c'"))
            == "system:careers"
        )
    command.upgrade(config, "head")
    engine.dispose()
