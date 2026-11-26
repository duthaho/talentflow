"""Opt-in checks for a disposable local PostgreSQL database only."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.modules.audit.persistence import AuditEvent
from app.modules.organization.application.set_requisition_publication import (
    SetRequisitionPublicationHandler,
)
from app.modules.organization.infrastructure.sqlalchemy_repository import (
    SqlAlchemyOrganizationRepository,
    SqlAlchemyUnitOfWork,
)


@pytest.mark.skipif(
    not os.environ.get("PUBLICATION_TEST_DATABASE_URL"),
    reason="Requires a disposable publication test database",
)
def test_postgres_migration_and_concurrent_publication(monkeypatch):
    url = os.environ["PUBLICATION_TEST_DATABASE_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config()
    config.set_main_option("script_location", "migrations")
    command.upgrade(config, "2d110f23a001")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tenants (id, name, slug, created_at) VALUES ('publication-tenant', 'Demo', 'publication-demo', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO users (id, created_at) VALUES ('publication-admin', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO requisitions (id, tenant_id, title, department, created_by, created_at) VALUES ('publication-job', 'publication-tenant', 'Engineer', 'Engineering', 'publication-admin', CURRENT_TIMESTAMP)"
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT published, published_at FROM requisitions WHERE id='publication-job'")
        ).one() == (False, None)
        definition = connection.scalar(
            text("SELECT indexdef FROM pg_indexes WHERE indexname='ix_requisitions_public'")
        )
        assert "published_at DESC" in definition and "WHERE published" in definition

    barrier = Barrier(2)

    def publish():
        with Session(engine) as session:
            handler = SetRequisitionPublicationHandler(
                SqlAlchemyOrganizationRepository(session), SqlAlchemyUnitOfWork(session)
            )
            barrier.wait(timeout=10)
            return handler.handle(
                tenant_id="publication-tenant",
                requisition_id="publication-job",
                published=True,
                actor_id="publication-admin",
                correlation_id="concurrent",
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.map(lambda _: publish(), range(2))
    assert first.published and first.published_at == second.published_at
    with Session(engine) as session:
        assert (
            len(
                session.scalars(
                    select(AuditEvent).where(AuditEvent.action == "requisition.published")
                ).all()
            )
            == 1
        )
    command.downgrade(config, "2d110f23a001")
    assert "published" not in {
        column["name"] for column in inspect(engine).get_columns("requisitions")
    }
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT title FROM requisitions WHERE id='publication-job'"))
            == "Engineer"
        )
    command.upgrade(config, "head")
    engine.dispose()
