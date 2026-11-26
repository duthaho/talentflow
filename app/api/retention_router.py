from datetime import UTC
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status

from app.api.schemas import (
    LegalHoldRequest,
    LegalHoldResponse,
    RetentionPolicyReadResponse,
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
from app.shared.attachment_storage import build_attachment_storage
from app.shared.database import SessionDep

router = APIRouter(tags=["retention"])


def _service(session: SessionDep, request: Request) -> RetentionService:
    return RetentionService(
        repository=SqlAlchemyRetentionRepository(
            session,
            attachment_storage=build_attachment_storage(request.app.state.runtime_settings),
        ),
        audit=SqlAlchemyAuditRecorder(session),
        unit_of_work=SqlAlchemyUnitOfWork(session),
    )


@router.put("/v1/retention-policy", response_model=RetentionPolicyResponse)
def set_retention_policy(
    payload: RetentionPolicyRequest,
    request: Request,
    session: SessionDep,
    actor: ActorContext = Depends(require("retention:manage")),
    correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
) -> RetentionPolicyResponse:
    policy = _service(session, request).set_policy(
        tenant_id=actor.tenant_id,
        retention_days=payload.retention_days,
        actor_id=actor.actor_id,
        correlation_id=correlation_id or str(uuid4()),
    )
    return RetentionPolicyResponse(retention_days=policy.retention_days)


@router.get("/v1/retention-policy", response_model=RetentionPolicyReadResponse)
def get_retention_policy(
    session: SessionDep,
    actor: ActorContext = Depends(require("retention:manage")),
) -> RetentionPolicyReadResponse:
    from app.modules.retention.persistence import RetentionPolicy as RetentionPolicyRecord

    record = session.get(RetentionPolicyRecord, actor.tenant_id)
    return RetentionPolicyReadResponse(retention_days=record.retention_days if record else None)


@router.put(
    "/v1/candidate-cases/{candidate_case_id}/legal-hold", status_code=status.HTTP_204_NO_CONTENT
)
def set_legal_hold(
    candidate_case_id: str,
    payload: LegalHoldRequest,
    request: Request,
    session: SessionDep,
    actor: ActorContext = Depends(require("retention:manage")),
    correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
) -> None:
    try:
        _service(session, request).set_legal_hold(
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


@router.get("/v1/candidate-cases/{candidate_case_id}/legal-hold", response_model=LegalHoldResponse)
def get_legal_hold(
    candidate_case_id: str,
    response: Response,
    session: SessionDep,
    actor: ActorContext = Depends(require("retention:manage")),
) -> LegalHoldResponse:
    from app.modules.candidates.persistence import CandidateCase
    from app.modules.retention.persistence import CandidateLegalHold

    candidate = session.get(CandidateCase, candidate_case_id)
    if candidate is None or candidate.tenant_id != actor.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Candidate case not found"
        )
    response.headers["Cache-Control"] = "private, no-store"
    hold = session.get(CandidateLegalHold, candidate_case_id)
    if hold is None or hold.tenant_id != actor.tenant_id:
        return LegalHoldResponse(held=False, reason=None, placed_at=None, placed_by=None)
    placed_at = hold.created_at
    if placed_at.tzinfo is None:
        placed_at = placed_at.replace(tzinfo=UTC)
    return LegalHoldResponse(
        held=True, reason=hold.reason, placed_at=placed_at, placed_by=hold.created_by
    )


@router.post("/v1/retention/purge", response_model=RetentionPurgeResponse)
def purge_due_candidates(
    request: Request,
    session: SessionDep,
    actor: ActorContext = Depends(require("retention:purge")),
    correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
) -> RetentionPurgeResponse:
    count = _service(session, request).purge_due(
        tenant_id=actor.tenant_id,
        actor_id=actor.actor_id,
        correlation_id=correlation_id or str(uuid4()),
    )
    return RetentionPurgeResponse(purged_count=count)
