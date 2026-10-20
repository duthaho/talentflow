from fastapi import APIRouter, Depends

from app.api.schemas import PipelineReportResponse
from app.modules.identity.security import ActorContext, require
from app.modules.reporting.application.pipeline_report import GetPipelineReportHandler
from app.modules.reporting.infrastructure.sqlalchemy_reader import SqlAlchemyPipelineReportReader
from app.shared.database import SessionDep

router = APIRouter(prefix="/v1/reports", tags=["reporting"])


@router.get("/pipeline", response_model=PipelineReportResponse)
def pipeline_report(
    session: SessionDep,
    actor: ActorContext = Depends(require("report:read")),
) -> PipelineReportResponse:
    report = GetPipelineReportHandler(SqlAlchemyPipelineReportReader(session)).handle(
        tenant_id=actor.tenant_id
    )
    return PipelineReportResponse(
        candidates={"total": report.candidate_total, "by_stage": report.candidates_by_stage},
        offers={"total": report.offer_total, "by_status": report.offers_by_status},
        interviews={
            "scheduled_total": report.scheduled_interview_total,
            "feedback_submitted_total": report.feedback_submitted_total,
        },
    )
