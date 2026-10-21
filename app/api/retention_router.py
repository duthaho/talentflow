from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.schemas import (
    LegalHoldRequest,
    RetentionPolicyRequest,
    RetentionPolicyResponse,
    RetentionPurgeResponse,
)
from app.modules.identity.security import ActorContext, require
from app.modules.retention.application.retention import CandidateNotFoundError, RetentionService
from app.modules.retention.infrastructure.sqlalchemy_repository import (
    SqlAlchemyAuditRecorder,
    SqlAlchemyRetentionRepository,
    SqlAlchemyUnitOfWork,
)
from app.shared.database import SessionDep

router = APIRouter(tags=["retention"])


def _service(session: SessionDep) -> RetentionService:
    return RetentionService(
        repository=SqlAlchemyRetentionRepository(session),
        audit=SqlAlchemyAuditRecorder(session),
        unit_of_work=SqlAlchemyUnitOfWork(session),
    )


@router.put("/v1/retention-policy", response_model=RetentionPolicyResponse)
def set_retention_policy(
    payload: RetentionPolicyRequest,
    session: SessionDep,
    actor: ActorContext = Depends(require("retention:manage")),
    correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
) -> RetentionPolicyResponse:
    policy = _service(session).set_policy(
        tenant_id=actor.tenant_id,
        retention_days=payload.retention_days,
        actor_id=actor.actor_id,
        correlation_id=correlation_id or str(uuid4()),
    )
    return RetentionPolicyResponse(retention_days=policy.retention_days)


@router.put(
    "/v1/candidate-cases/{candidate_case_id}/legal-hold", status_code=status.HTTP_204_NO_CONTENT
)
def set_legal_hold(
    candidate_case_id: str,
    payload: LegalHoldRequest,
    session: SessionDep,
    actor: ActorContext = Depends(require("retention:manage")),
    correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
) -> None:
    try:
        _service(session).set_legal_hold(
            tenant_id=actor.tenant_id,
            candidate_case_id=candidate_case_id,
            held=payload.held,
            reason=payload.reason,
            actor_id=actor.actor_id,
            correlation_id=correlation_id or str(uuid4()),
        )
    except CandidateNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Candidate case not found"
        ) from error


@router.post("/v1/retention/purge", response_model=RetentionPurgeResponse)
def purge_due_candidates(
    session: SessionDep,
    actor: ActorContext = Depends(require("retention:purge")),
    correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
) -> RetentionPurgeResponse:
    count = _service(session).purge_due(
        tenant_id=actor.tenant_id,
        actor_id=actor.actor_id,
        correlation_id=correlation_id or str(uuid4()),
    )
    return RetentionPurgeResponse(purged_count=count)
