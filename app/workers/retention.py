import logging
import time
from collections.abc import Callable
from uuid import uuid4

from sqlalchemy import Connection, Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.modules.attachments.application.ports import AttachmentStorage
from app.modules.retention.application.retention import RetentionService
from app.modules.retention.infrastructure.sqlalchemy_repository import (
    SqlAlchemyAuditRecorder,
    SqlAlchemyRetentionRepository,
    SqlAlchemyUnitOfWork,
)
from app.shared.attachment_storage import build_attachment_storage
from app.shared.database import build_session_factory
from app.shared.observability import configure_logging, configure_telemetry
from app.shared.settings import settings
from app.shared.worker_runtime import WorkerLoop

logger = logging.getLogger(__name__)
_LOCK_NAME = "talentflow:retention"


class ScheduledRetentionCycle:
    """Runs retention at most once per schedule, protected by a database-wide lock."""

    def __init__(
        self,
        sessions: sessionmaker,
        *,
        schedule_seconds: float,
        batch_size: int,
        storage: AttachmentStorage,
    ):
        self._sessions = sessions
        self._schedule_seconds = schedule_seconds
        self._batch_size = batch_size
        self._storage = storage
        self._next_run = 0.0

    def __call__(self, *, should_stop: Callable[[], bool] | None = None) -> int:
        if time.monotonic() < self._next_run:
            return 0
        self._next_run = time.monotonic() + self._schedule_seconds
        stopping = should_stop or (lambda: False)
        engine: Engine = self._sessions.kw["bind"]
        with engine.connect() as connection:
            if not self._acquire_lock(connection):
                logger.info(
                    "retention_worker_lock_contended",
                    extra={"event": "retention_worker_lock_contended"},
                )
                return 0
            # pg_try_advisory_lock starts a transaction. Commit it before binding the
            # ORM session so its per-tenant commits are durable; session-level locks
            # remain held across the commit on this dedicated connection.
            connection.commit()
            try:
                with Session(bind=connection, autoflush=False, expire_on_commit=False) as session:
                    repository = SqlAlchemyRetentionRepository(
                        session, attachment_storage=self._storage
                    )
                    purged = 0
                    for tenant_id in repository.policy_tenant_ids(limit=self._batch_size):
                        if stopping():
                            break
                        service = RetentionService(
                            repository=repository,
                            audit=SqlAlchemyAuditRecorder(session),
                            unit_of_work=SqlAlchemyUnitOfWork(session),
                        )
                        purged += service.purge_due(
                            tenant_id=tenant_id,
                            actor_id="system:retention",
                            correlation_id=str(uuid4()),
                        )
                logger.info(
                    "retention_worker_completed",
                    extra={"event": "retention_worker_completed", "purged": purged},
                )
                return purged
            finally:
                if connection.in_transaction():
                    connection.rollback()
                self._release_lock(connection)

    @staticmethod
    def _acquire_lock(connection: Connection) -> bool:
        # SQLite is used only for local unit tests; PostgreSQL coordinates compose replicas.
        if connection.dialect.name != "postgresql":
            return True
        return bool(
            connection.scalar(
                text("SELECT pg_try_advisory_lock(hashtext(:name))"), {"name": _LOCK_NAME}
            )
        )

    @staticmethod
    def _release_lock(connection: Connection) -> None:
        if connection.dialect.name == "postgresql":
            connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:name))"), {"name": _LOCK_NAME}
            )


def main() -> None:
    configure_telemetry(settings)
    configure_logging()
    sessions = build_session_factory(settings.database_url)
    cycle = ScheduledRetentionCycle(
        sessions,
        schedule_seconds=settings.retention_schedule_seconds,
        batch_size=settings.retention_worker_batch_size,
        storage=build_attachment_storage(settings),
    )
    loop: WorkerLoop

    def run_cycle() -> int:
        return cycle(should_stop=loop.stopping)

    def ready() -> None:
        with sessions() as session:
            session.execute(text("SELECT 1"))

    try:
        loop = WorkerLoop(
            name="retention",
            cycle=run_cycle,
            readiness_check=ready,
            poll_seconds=settings.worker_poll_seconds,
            max_backoff_seconds=settings.worker_max_backoff_seconds,
            grace_seconds=settings.worker_shutdown_grace_seconds,
            probe_port=8003,
        )
        loop.run()
    finally:
        sessions.kw["bind"].dispose()


if __name__ == "__main__":
    main()
