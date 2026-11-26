from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_existing_requisitions_default_unpublished_and_downgrade_preserves_rows(
    tmp_path, monkeypatch
):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config()
    config.set_main_option("script_location", "migrations")
    command.upgrade(config, "2d110f23a001")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tenants (id, name, slug, created_at) VALUES ('tenant', 'Demo', 'demo', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text("INSERT INTO users (id, created_at) VALUES ('admin', CURRENT_TIMESTAMP)")
        )
        connection.execute(
            text(
                "INSERT INTO requisitions (id, tenant_id, title, department, created_by, created_at) VALUES ('job', 'tenant', 'Engineer', 'Engineering', 'admin', CURRENT_TIMESTAMP)"
            )
        )
    command.upgrade(config, "d126a001")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT published, published_at FROM requisitions WHERE id='job'")
        ).one() == (0, None)
        index_sql = connection.scalar(
            text("SELECT sql FROM sqlite_master WHERE name='ix_requisitions_public'")
        )
        assert "published_at DESC" in index_sql and "WHERE published" in index_sql
    command.downgrade(config, "2d110f23a001")
    assert "published" not in {
        column["name"] for column in inspect(engine).get_columns("requisitions")
    }
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT title FROM requisitions WHERE id='job'")) == "Engineer"
        )
    command.upgrade(config, "head")
    engine.dispose()
