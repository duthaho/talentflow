from app.modules.candidates.application.create_candidate import (
    CreateCandidateCommand,
    CreateCandidateHandler,
)
from app.modules.candidates.domain.candidate_case import CandidateCase


class FakeCandidates:
    def __init__(self) -> None:
        self.added: CandidateCase | None = None

    def email_exists(self, *, tenant_id: str, email: str) -> bool:
        return False

    def add(
        self,
        *,
        candidate: CandidateCase,
        first_name: str,
        last_name: str,
        email: str,
        created_by: str,
    ) -> None:
        self.added = candidate


class FakeRequisitions:
    def exists(self, *, requisition_id: str, tenant_id: str) -> bool:
        return True


class FakeAudit:
    def candidate_created(self, **_: object) -> None:
        pass


class FakeUnitOfWork:
    committed = False

    def commit(self) -> None:
        self.committed = True


def test_create_candidate_handler_normalizes_email_and_commits() -> None:
    candidates = FakeCandidates()
    unit_of_work = FakeUnitOfWork()
    created = CreateCandidateHandler(
        candidates=candidates,
        requisitions=FakeRequisitions(),
        audit=FakeAudit(),
        unit_of_work=unit_of_work,
    ).handle(
        CreateCandidateCommand(
            tenant_id="tenant",
            requisition_id="requisition",
            first_name=" Ada ",
            last_name=" Lovelace ",
            email=" ADA@EXAMPLE.COM ",
            actor_id="recruiter",
            correlation_id="correlation",
        )
    )

    assert candidates.added is not None
    assert created.email == "ada@example.com"
    assert created.candidate.stage.value == "applied"
    assert unit_of_work.committed
