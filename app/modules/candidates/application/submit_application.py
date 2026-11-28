"""Anonymous intake; all I/O goes through ports owned by candidates."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from email.errors import HeaderParseError
from email.headerregistry import Address
from typing import Protocol

from app.modules.candidates.application.consent import VERSION, render_consent
from app.modules.candidates.domain.candidate_case import CandidateCase

SYSTEM_ACTOR = "system:careers"


class ApplicationError(Exception):
    def __init__(self, status: int, detail: str, retry_after: int | None = None):
        self.status, self.detail, self.retry_after = status, detail, retry_after


class DuplicateApplication(Exception):
    """The unique tenant/email insert lost a concurrent race."""


@dataclass(frozen=True)
class PublicTenant:
    id: str
    name: str
    slug: str
    retention_days: int | None


@dataclass(frozen=True)
class Application:
    slug: str
    requisition_id: str
    fields: dict[str, str]
    filename: str
    content_type: str
    content: bytes
    correlation_id: str


class CvIntake(Protocol):
    def inspect(self, application: Application) -> object: ...
    def attach(self, cv: object, candidate: CandidateCase, correlation_id: str) -> str: ...
    def discard(self, *, storage_key: str) -> None: ...


class ApplicationRepository(Protocol):
    def tenant(self, slug: str) -> PublicTenant | None: ...
    def is_published(self, tenant_id: str, requisition_id: str) -> bool: ...
    def find_id_by_email(self, tenant_id: str, email: str) -> str | None: ...
    def add(self, candidate: CandidateCase, fields: dict[str, str]) -> None: ...
    def add_consent(self, candidate: CandidateCase, text: str, accepted_at: datetime) -> None: ...
    def reapply(
        self, tenant_id: str, candidate_id: str, requisition_id: str, correlation_id: str
    ) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class ApplicationThrottle(Protocol):
    def consume_email(self, tenant_id: str, email: str) -> None: ...


class SubmitApplicationHandler:
    def __init__(
        self, repository: ApplicationRepository, intake: CvIntake, throttle: ApplicationThrottle
    ):
        self.repository, self.intake, self.throttle = repository, intake, throttle

    def handle(self, application: Application) -> str:
        fields = dict(application.fields)
        if fields.get("website"):
            return "honeypot"
        tenant = self.repository.tenant(application.slug)
        if tenant is None or not self.repository.is_published(
            tenant.id, application.requisition_id
        ):
            raise ApplicationError(404, "Requisition not found")
        for name in ("first_name", "last_name"):
            raw = fields.get(name, "")
            value = raw.strip()
            if not 1 <= len(value) <= 100 or any(
                unicodedata.category(c) in {"Cc", "Cf"} for c in raw
            ):
                raise ApplicationError(
                    422, "Names must contain 1–100 characters without control or bidi characters"
                )
            fields[name] = value
        email = fields.get("email", "").strip().lower()
        if not valid_email(email):
            raise ApplicationError(422, "A valid email is required")
        fields["email"] = email
        if fields.get("consent_version") != VERSION or fields.get("consent_accepted") != "true":
            raise ApplicationError(
                422, "Consent is required; reload the consent text and accept it"
            )
        self.throttle.consume_email(tenant.id, email)
        cv = self.intake.inspect(application)
        existing = self.repository.find_id_by_email(tenant.id, email)
        if existing:
            self._reapply(tenant.id, existing, application)
            return "reapplied"
        candidate = CandidateCase.open(
            tenant_id=tenant.id, requisition_id=application.requisition_id
        )
        storage_key = None
        try:
            self.repository.add(candidate, fields)  # Flush before writing an object.
            storage_key = self.intake.attach(cv, candidate, application.correlation_id)
            self.repository.add_consent(
                candidate, render_consent(tenant.name, tenant.retention_days), datetime.now(UTC)
            )
            self.repository.commit()
        except DuplicateApplication:
            self.repository.rollback()
            if storage_key:
                self.intake.discard(storage_key=storage_key)
            existing = self.repository.find_id_by_email(tenant.id, email)
            if not existing:
                raise
            self._reapply(tenant.id, existing, application)
            return "reapplied"
        except Exception:
            self.repository.rollback()
            if storage_key:
                self.intake.discard(storage_key=storage_key)
            raise
        return "created"

    def _reapply(self, tenant_id: str, candidate_id: str, application: Application) -> None:
        self.repository.reapply(
            tenant_id, candidate_id, application.requisition_id, application.correlation_id
        )
        self.repository.commit()


def valid_email(email: str) -> bool:
    if len(email) > 320 or any(
        c.isspace() or unicodedata.category(c) in {"Cc", "Cf"} for c in email
    ):
        return False
    try:
        address = Address(addr_spec=email)
        domain = address.domain.encode("idna").decode("ascii")
    except (ValueError, IndexError, UnicodeError, HeaderParseError):
        return False
    return bool(
        address.username
        and len(address.username) <= 64
        and len(domain) <= 253
        and re.fullmatch(
            r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
            domain,
        )
    )
