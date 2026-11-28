from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.modules.candidates.persistence import CandidateCase
from app.modules.notifications.persistence import NotificationDelivery
from app.modules.organization.persistence import Membership, User


class EmailAdapter(Protocol):
    def send(self, *, recipient: str, subject: str, text: str) -> None: ...


class EmailDeliverySender:
    """Maps a notification delivery into an email through the application port."""

    def __init__(self, sessions: sessionmaker, adapter: EmailAdapter):
        self.sessions = sessions
        self.adapter = adapter

    def __call__(self, delivery: NotificationDelivery) -> None:
        with self.sessions() as session:
            recipient = session.get(User, delivery.recipient_id)
            if (
                delivery.kind == "onboarding_ready"
                and session.scalar(
                    select(Membership.id).where(
                        Membership.tenant_id == delivery.tenant_id,
                        Membership.user_id == delivery.recipient_id,
                    )
                )
                is None
            ):
                return
            if recipient is None or not recipient.email:
                raise ValueError("Notification recipient has no email address")
        if delivery.kind == "onboarding_ready":
            with self.sessions() as session:
                candidate = session.get(CandidateCase, delivery.payload_json["candidate_case_id"])
                name = (
                    f"{candidate.first_name} {candidate.last_name}"
                    if candidate is not None
                    and candidate.tenant_id == delivery.tenant_id
                    and candidate.anonymized_at is None
                    else "a new hire"
                )
            self.adapter.send(
                recipient=recipient.email,
                subject="TalentFlow onboarding ready",
                text=f"Onboarding for {name} is ready. Start date: {delivery.payload_json['start_date']}. Tasks: {', '.join(delivery.payload_json['task_keys'])}.",
            )
            return
        decision = str(delivery.payload_json.get("decision", "updated"))
        self.adapter.send(
            recipient=recipient.email,
            subject="TalentFlow offer approval update",
            text=f"An offer approval was recorded with decision: {decision}.",
        )
