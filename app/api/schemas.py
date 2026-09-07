from __future__ import annotations

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


class AuditEventResponse(BaseModel):
    id: str
    action: str
    aggregate_type: str
    aggregate_id: str
    correlation_id: str
