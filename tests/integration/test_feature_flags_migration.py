import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_pause_table_expand_constraint_and_downgrade(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'pauses.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO webhook_delivery_pauses VALUES ('tenant', CURRENT_TIMESTAMP, 'flag_off')"
            )
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO webhook_delivery_pauses VALUES ('bad', CURRENT_TIMESTAMP, 'unknown')"
                )
            )
    command.downgrade(config, "d127a001")
    assert not inspect(engine).has_table("webhook_delivery_pauses")
    assert inspect(engine).has_table("webhook_deliveries")
    command.upgrade(config, "head")
    assert inspect(engine).has_table("webhook_delivery_pauses")
    engine.dispose()
