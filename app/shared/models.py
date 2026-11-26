"""Compatibility imports for persistence records owned by bounded contexts."""

from app.modules.attachments.infrastructure.models import Attachment
from app.modules.audit.infrastructure.models import AuditEvent
from app.modules.calendar.infrastructure.models import CalendarSubscription
from app.modules.candidates.infrastructure.models import CandidateCase
from app.modules.interviews.infrastructure.models import Interview, InterviewFeedback
from app.modules.notifications.infrastructure.models import NotificationDelivery, OutboxEvent
from app.modules.offers.infrastructure.models import ApprovalDecision, Offer
from app.modules.organization.infrastructure.models import Membership, Requisition, Tenant, User
from app.modules.retention.infrastructure.models import CandidateLegalHold, RetentionPolicy
from app.shared.database import Base
from app.shared.idempotency import IdempotencyRecord

__all__ = [
    "ApprovalDecision",
    "Attachment",
    "AuditEvent",
    "Base",
    "CalendarSubscription",
    "CandidateCase",
    "CandidateLegalHold",
    "IdempotencyRecord",
    "Interview",
    "InterviewFeedback",
    "Membership",
    "NotificationDelivery",
    "Offer",
    "OutboxEvent",
    "Requisition",
    "RetentionPolicy",
    "Tenant",
    "User",
]
