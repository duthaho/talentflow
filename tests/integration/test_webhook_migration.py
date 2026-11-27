import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_expand_downgrade_and_original_purge_with_two_redeliveries(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config()
    config.set_main_option("script_location", "migrations")
    command.upgrade(config, "d126a001")
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(
            text(
                "INSERT INTO webhook_endpoints (id,tenant_id,url,status,created_by,created_at,updated_at) VALUES ('e','t','https://receiver.example','enabled','admin',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO webhook_events (tenant_id,event_id,event_type,body,occurred_at,received_at) VALUES ('t','event','offer.created.v1','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        for ident, kind, original, actor in [
            ("original", "fanout", None, None),
            ("retry-1", "redelivery", "original", "admin"),
            ("retry-2", "redelivery", "original", "admin"),
        ]:
            connection.execute(
                text(
                    "INSERT INTO webhook_deliveries (id,tenant_id,endpoint_id,event_id,event_type,status,kind,redelivery_of_id,requested_by,created_at,completed_at) VALUES (:id,'t','e','event','offer.created.v1','succeeded',:kind,:original,:actor,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                ),
                dict(id=ident, kind=kind, original=original, actor=actor),
            )
        connection.execute(text("DELETE FROM webhook_deliveries WHERE id='original'"))
        assert connection.execute(
            text("SELECT kind,redelivery_of_id FROM webhook_deliveries ORDER BY id")
        ).all() == [("redelivery", None), ("redelivery", None)]
        # Fanout uniqueness still applies; redeliveries with NULL lineage do not become fanout.
        connection.execute(
            text(
                "INSERT INTO webhook_deliveries (id,tenant_id,endpoint_id,event_id,event_type,status,kind,created_at) VALUES ('new-original','t','e','event','offer.created.v1','succeeded','fanout',CURRENT_TIMESTAMP)"
            )
        )
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO webhook_subscriptions (tenant_id,endpoint_id,event_type,created_at) VALUES ('other','e','offer.created.v1',CURRENT_TIMESTAMP)"
                )
            )
    command.downgrade(config, "d126a001")
    assert not inspect(engine).has_table("webhook_endpoints")
    assert inspect(engine).has_table("requisitions")
    command.upgrade(config, "head")
    assert inspect(engine).has_table("webhook_delivery_attempts")
    engine.dispose()
