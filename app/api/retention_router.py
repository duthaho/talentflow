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
    request: Request,
    session: SessionDep,
    actor: ActorContext = Depends(require("retention:manage")),
) -> RetentionPolicyReadResponse:
    retention_days = _service(session, request).get_policy(tenant_id=actor.tenant_id)
    return RetentionPolicyReadResponse(retention_days=retention_days)


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
    request: Request,
    response: Response,
    session: SessionDep,
    actor: ActorContext = Depends(require("retention:manage")),
) -> LegalHoldResponse:
    try:
        hold = _service(session, request).get_legal_hold(
            tenant_id=actor.tenant_id, candidate_case_id=candidate_case_id
        )
    except CandidateNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Candidate case not found"
        ) from error
    response.headers["Cache-Control"] = "private, no-store"
    return LegalHoldResponse(**hold.__dict__)


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
