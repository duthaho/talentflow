from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CreateTenantRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9-]{2,80}$")
    admin_id: str = Field(min_length=1, max_length=128)


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str


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


class OfferResponse(BaseModel):
    id: str
    status: str
    approval_step: int
    version: int
    candidate_stage: str


class AuditEventResponse(BaseModel):
    id: str
    action: str
    aggregate_type: str
    aggregate_id: str
    correlation_id: str
