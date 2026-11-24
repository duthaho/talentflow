import logging
import time
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.modules.attachments.infrastructure.filesystem_storage import LocalAttachmentStorage
from app.modules.retention.application.retention import RetentionService
from app.modules.retention.infrastructure.sqlalchemy_repository import (
    SqlAlchemyAuditRecorder,
    SqlAlchemyRetentionRepository,
    SqlAlchemyUnitOfWork,
)
from app.shared.database import build_session_factory
from app.shared.observability import configure_logging
from app.shared.settings import settings
from app.shared.worker_runtime import WorkerLoop

logger = logging.getLogger(__name__)
_LOCK_NAME = "talentflow:retention"


class ScheduledRetentionCycle:
    """Runs retention at most once per schedule, protected by a database-wide lock."""

    def __init__(
        self, sessions: sessionmaker, *, schedule_seconds: float, batch_size: int, storage: str
    ):
        self._sessions = sessions
        self._schedule_seconds = schedule_seconds
        self._batch_size = batch_size
        self._storage = LocalAttachmentStorage(storage)
        self._next_run = 0.0

    def __call__(self) -> int:
        if time.monotonic() < self._next_run:
            return 0
        self._next_run = time.monotonic() + self._schedule_seconds
        with self._sessions() as session:
            if not self._acquire_lock(session):
                logger.info(
                    "retention_worker_lock_contended",
                    extra={"event": "retention_worker_lock_contended"},
                )
                return 0
            try:
                repository = SqlAlchemyRetentionRepository(
                    session, attachment_storage=self._storage
                )
                purged = 0
                for tenant_id in repository.policy_tenant_ids(limit=self._batch_size):
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
                self._release_lock(session)

    @staticmethod
    def _acquire_lock(session: object) -> bool:
        # SQLite is used only for local unit tests; PostgreSQL coordinates compose replicas.
        if session.bind.dialect.name != "postgresql":
            return True
        return bool(
            session.scalar(
                text("SELECT pg_try_advisory_lock(hashtext(:name))"), {"name": _LOCK_NAME}
            )
        )

    @staticmethod
    def _release_lock(session: object) -> None:
        if session.bind.dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_unlock(hashtext(:name))"), {"name": _LOCK_NAME}
            )


def main() -> None:
    configure_logging()
    sessions = build_session_factory(settings.database_url)
    cycle = ScheduledRetentionCycle(
        sessions,
        schedule_seconds=settings.retention_schedule_seconds,
        batch_size=settings.retention_worker_batch_size,
        storage=settings.attachment_storage_root,
    )

    def ready() -> None:
        with sessions() as session:
            session.execute(text("SELECT 1"))

    try:
        WorkerLoop(
            name="retention",
            cycle=cycle,
            readiness_check=ready,
            poll_seconds=settings.worker_poll_seconds,
            max_backoff_seconds=settings.worker_max_backoff_seconds,
            grace_seconds=settings.worker_shutdown_grace_seconds,
            probe_port=8003,
        ).run()
    finally:
        sessions.kw["bind"].dispose()


if __name__ == "__main__":
    main()
