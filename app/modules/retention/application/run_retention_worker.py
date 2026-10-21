import logging
from uuid import uuid4

from app.modules.retention.application.retention import RetentionService
from app.modules.retention.infrastructure.sqlalchemy_repository import (
    SqlAlchemyAuditRecorder,
    SqlAlchemyRetentionRepository,
    SqlAlchemyUnitOfWork,
)
from app.shared.database import build_session_factory
from app.shared.observability import configure_logging
from app.shared.settings import settings

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    sessions = build_session_factory(settings.database_url)
    purged = 0
    try:
        with sessions() as session:
            repository = SqlAlchemyRetentionRepository(
                session, attachment_storage_root=settings.attachment_storage_root
            )
            tenant_ids = repository.policy_tenant_ids(limit=settings.retention_worker_batch_size)
            for tenant_id in tenant_ids:
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
    finally:
        sessions.kw["bind"].dispose()


if __name__ == "__main__":
    main()
