from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PipelineReport:
    candidate_total: int
    candidates_by_stage: dict[str, int]
    offer_total: int
    offers_by_status: dict[str, int]
    scheduled_interview_total: int
    feedback_submitted_total: int


class PipelineReportReader(Protocol):
    def pipeline_for_tenant(self, *, tenant_id: str) -> PipelineReport: ...


class GetPipelineReportHandler:
    def __init__(self, reader: PipelineReportReader):
        self._reader = reader

    def handle(self, *, tenant_id: str) -> PipelineReport:
        return self._reader.pipeline_for_tenant(tenant_id=tenant_id)
