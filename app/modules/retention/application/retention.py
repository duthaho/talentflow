from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

TERMINAL_STAGES = frozenset({"rejected", "withdrawn"})


class CandidateNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class RetentionPolicy:
    tenant_id: str
    retention_days: int


class RetentionRepository(Protocol):
    def set_policy(self, *, tenant_id: str, retention_days: int) -> RetentionPolicy: ...

    def candidate_exists(self, *, tenant_id: str, candidate_case_id: str) -> bool: ...

    def set_legal_hold(
        self,
        *,
        tenant_id: str,
        candidate_case_id: str,
        held: bool,
        reason: str | None,
        actor_id: str,
    ) -> None: ...

    def purge_due(self, *, tenant_id: str, now: datetime) -> list[str]: ...


class AuditRecorder(Protocol):
    def record(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        action: str,
        aggregate_type: str,
        aggregate_id: str,
        correlation_id: str,
        metadata: dict[str, object],
    ) -> None: ...


class UnitOfWork(Protocol):
    def commit(self) -> None: ...


class RetentionService:
    def __init__(
        self, *, repository: RetentionRepository, audit: AuditRecorder, unit_of_work: UnitOfWork
    ) -> None:
        self._repository = repository
        self._audit = audit
        self._unit_of_work = unit_of_work

    def set_policy(
        self, *, tenant_id: str, retention_days: int, actor_id: str, correlation_id: str
    ) -> RetentionPolicy:
        policy = self._repository.set_policy(tenant_id=tenant_id, retention_days=retention_days)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="retention_policy.updated",
            aggregate_type="retention_policy",
            aggregate_id=tenant_id,
            correlation_id=correlation_id,
            metadata={"retention_days": retention_days},
        )
        self._unit_of_work.commit()
        return policy

    def set_legal_hold(
        self,
        *,
        tenant_id: str,
        candidate_case_id: str,
        held: bool,
        reason: str | None,
        actor_id: str,
        correlation_id: str,
    ) -> None:
        if not self._repository.candidate_exists(
            tenant_id=tenant_id, candidate_case_id=candidate_case_id
        ):
            raise CandidateNotFoundError(candidate_case_id)
        self._repository.set_legal_hold(
            tenant_id=tenant_id,
            candidate_case_id=candidate_case_id,
            held=held,
            reason=reason,
            actor_id=actor_id,
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="candidate_case.legal_hold_set"
            if held
            else "candidate_case.legal_hold_released",
            aggregate_type="candidate_case",
            aggregate_id=candidate_case_id,
            correlation_id=correlation_id,
            metadata={},
        )
        self._unit_of_work.commit()

    def purge_due(self, *, tenant_id: str, actor_id: str, correlation_id: str) -> int:
        candidate_ids = self._repository.purge_due(tenant_id=tenant_id, now=datetime.now(UTC))
        for candidate_id in candidate_ids:
            self._audit.record(
                tenant_id=tenant_id,
                actor_id=actor_id,
                action="candidate_case.retention_purged",
                aggregate_type="candidate_case",
                aggregate_id=candidate_id,
                correlation_id=correlation_id,
                metadata={"pii": "anonymized"},
            )
        self._unit_of_work.commit()
        return len(candidate_ids)
