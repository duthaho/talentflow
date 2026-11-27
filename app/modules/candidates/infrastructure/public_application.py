from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.modules.audit.persistence import AuditEvent
from app.modules.candidates.application.consent import VERSION
from app.modules.candidates.application.submit_application import (
    SYSTEM_ACTOR,
    ApplicationError,
    DuplicateApplication,
    PublicTenant,
)
from app.modules.candidates.infrastructure.sqlalchemy_repository import SqlAlchemyAuditRecorder
from app.modules.candidates.persistence import CandidateCase as Record
from app.modules.candidates.persistence import CandidateConsent
from app.modules.organization.persistence import Requisition, Tenant
from app.modules.retention.persistence import RetentionPolicy


class SqlAlchemyApplicationRepository:
    def __init__(self, session):
        self.session = session

    def tenant(self, slug):
        record = self.session.scalar(select(Tenant).where(Tenant.slug == slug))
        if record is None:
            return None
        days = self.session.scalar(
            select(RetentionPolicy.retention_days).where(RetentionPolicy.tenant_id == record.id)
        )
        return PublicTenant(record.id, record.name, record.slug, days)

    def is_published(self, tenant_id, requisition_id):
        return (
            self.session.scalar(
                select(Requisition.id).where(
                    Requisition.tenant_id == tenant_id,
                    Requisition.id == requisition_id,
                    Requisition.published.is_(True),
                )
            )
            is not None
        )

    def find_id_by_email(self, tenant_id, email):
        return self.session.scalar(
            select(Record.id).where(
                Record.tenant_id == tenant_id, func.lower(Record.email) == email
            )
        )

    def add(self, candidate, fields):
        self.session.add(
            Record(
                id=candidate.id,
                tenant_id=candidate.tenant_id,
                requisition_id=candidate.requisition_id,
                first_name=fields["first_name"],
                last_name=fields["last_name"],
                email=fields["email"],
                stage="applied",
                source="careers",
                created_by=SYSTEM_ACTOR,
            )
        )
        try:
            self.session.flush()
        except IntegrityError as error:
            # Only the known unique constraint is an anti-enumeration race.
            constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            if (
                constraint == "uq_candidate_case_tenant_email"
                or "candidate_cases.tenant_id, candidate_cases.email" in str(error.orig)
            ):
                raise DuplicateApplication() from error
            raise

    def add_consent(self, candidate, text, accepted_at):
        self.session.add(
            CandidateConsent(
                candidate_case_id=candidate.id,
                tenant_id=candidate.tenant_id,
                version=VERSION,
                text=text,
                accepted_at=accepted_at,
            )
        )
        SqlAlchemyAuditRecorder(self.session).candidate_created(
            candidate=candidate,
            actor_id=SYSTEM_ACTOR,
            correlation_id=self.session.info.get("careers_correlation_id", "careers"),
        )

    def reapply(self, tenant_id, candidate_id, requisition_id, correlation_id):
        self.session.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_id=SYSTEM_ACTOR,
                action="candidate_case.reapplied",
                aggregate_type="candidate_case",
                aggregate_id=candidate_id,
                correlation_id=correlation_id,
                metadata_json={"requisition_id": requisition_id},
            )
        )

    def commit(self):
        self.session.commit()

    def rollback(self):
        self.session.rollback()


class RedisApplicationThrottle:
    def __init__(self, limiter, limit):
        self.limiter, self.limit = limiter, limit

    def consume_email(self, tenant_id, email):
        key = sha256((tenant_id + email).encode()).hexdigest()
        consume(self.limiter, f"talentflow:careers:email:{key}", self.limit, 86400)


def consume(limiter, key, limit, window):
    try:
        decision = limiter.consume(key, limit=limit, window_seconds=window)
    except Exception as error:
        raise ApplicationError(503, "Application service temporarily unavailable") from error
    if not decision.allowed:
        raise ApplicationError(429, "Rate limit exceeded", decision.retry_after)
