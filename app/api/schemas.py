from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CreateTenantRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9-]{2,80}$")
    admin_id: str = Field(min_length=1, max_length=128)


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str


class CurrentActorResponse(BaseModel):
    user_id: str
    email: str | None
    display_name: None = None
    tenant_id: str
    tenant_name: str
    role: Literal["tenant_admin", "recruiter", "auditor", "hiring_manager", "interviewer"]
    permissions: list[str]


class CreateRequisitionRequest(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    department: str = Field(min_length=2, max_length=120)


class RequisitionResponse(BaseModel):
    id: str
    title: str
    department: str


class CreateCandidateCaseRequest(BaseModel):
    requisition_id: str = Field(min_length=36, max_length=36)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=320)


class TransitionCandidateCaseRequest(BaseModel):
    target_stage: str = Field(min_length=3, max_length=40)
    expected_version: int = Field(ge=1)


class CandidateCaseResponse(BaseModel):
    id: str
    requisition_id: str
    first_name: str
    last_name: str
    email: str
    stage: str
    version: int


class CandidateListItem(BaseModel):
    id: str
    requisition_id: str
    first_name: str
    last_name: str
    email: str
    stage: str
    version: int


class CandidateListResponse(BaseModel):
    items: list[CandidateListItem]
    next_cursor: str | None
    total: int


class CreateInterviewRequest(BaseModel):
    interviewer_id: str = Field(min_length=1, max_length=128)
    scheduled_at: datetime


class InterviewResponse(BaseModel):
    id: str
    candidate_case_id: str
    interviewer_id: str
    scheduled_at: datetime


class SubmitFeedbackRequest(BaseModel):
    score: int = Field(ge=1, le=5)
    recommendation: str = Field(pattern=r"^(strong_hire|hire|no_hire|strong_no_hire)$")
    comments: str = Field(min_length=1, max_length=5000)


class FeedbackResponse(BaseModel):
    id: str
    interview_id: str
    score: int
    recommendation: str
    comments: str


class CreateOfferRequest(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    annual_salary: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class ApproveOfferRequest(BaseModel):
    decision: str = Field(pattern=r"^(approved|rejected)$")
    expected_version: int = Field(ge=1)
    reason: str | None = None

    @model_validator(mode="after")
    def validate_reason(self) -> ApproveOfferRequest:
        if self.reason is not None:
            self.reason = self.reason.strip() or None
        if self.reason is not None and len(self.reason) > 500:
            raise ValueError("Reason must be at most 500 characters")
        if self.decision == "rejected" and self.reason is None:
            raise ValueError("A rejection requires a reason")
        return self


class OfferResponse(BaseModel):
    id: str
    status: str
    approval_step: int
    version: int
    candidate_stage: str


class OfferSummaryResponse(BaseModel):
    id: str
    candidate_case_id: str
    title: str
    annual_salary: int
    currency: str
    status: str
    approval_step: int
    awaiting_role: str | None
    version: int
    can_decide: bool


class OfferPageResponse(BaseModel):
    items: list[OfferSummaryResponse]
    next_cursor: str | None
    total: int


class OfferDecisionResponse(BaseModel):
    step: int
    decision: str
    actor_id: str
    decided_at: datetime | None
    reason: str | None


class OfferDetailResponse(OfferSummaryResponse):
    decisions: list[OfferDecisionResponse]


class CreateCalendarSubscriptionRequest(BaseModel):
    interviewer_id: str = Field(min_length=1, max_length=128)


class CalendarSubscriptionResponse(BaseModel):
    id: str
    interviewer_id: str
    feed_url: str
    expires_at: datetime


class RetentionPolicyRequest(BaseModel):
    retention_days: int = Field(ge=1, le=3650)


class RetentionPolicyResponse(BaseModel):
    retention_days: int


class LegalHoldRequest(BaseModel):
    held: bool
    reason: str | None = Field(default=None, min_length=1, max_length=500)


class RetentionPurgeResponse(BaseModel):
    purged_count: int


class AttachmentResponse(BaseModel):
    id: str
    document_type: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: datetime


class PipelineCandidateSummary(BaseModel):
    total: int
    by_stage: dict[str, int]


class PipelineOfferSummary(BaseModel):
    total: int
    by_status: dict[str, int]


class PipelineInterviewSummary(BaseModel):
    scheduled_total: int
    feedback_submitted_total: int


class PipelineReportResponse(BaseModel):
    candidates: PipelineCandidateSummary
    offers: PipelineOfferSummary
    interviews: PipelineInterviewSummary


class AuditEventResponse(BaseModel):
    id: str
    action: str
    aggregate_type: str
    aggregate_id: str
    correlation_id: str
