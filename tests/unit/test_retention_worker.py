from datetime import UTC, datetime, timedelta
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from sqlalchemy import text

from app.shared.database import build_session_factory
from app.shared.models import Base, CandidateCase, Requisition, RetentionPolicy, Tenant, User
from app.workers.retention import ScheduledRetentionCycle


class PostgresConnection:
    def __init__(self, locks: set[str]) -> None:
        self.dialect = SimpleNamespace(name="postgresql")
        self.calls: list[str] = []
        self._locks = locks

    def scalar(self, statement, params):
        self.calls.append(str(statement))
        assert params == {"name": "talentflow:retention"}
        if "pg_try" in str(statement) and params["name"] not in self._locks:
            self._locks.add(params["name"])
            return True
        return False

    def execute(self, statement, params):
        self.calls.append(str(statement))
        assert params == {"name": "talentflow:retention"}
        self._locks.discard(params["name"])


def test_retention_second_postgres_connection_skips_a_held_lock() -> None:
    locks: set[str] = set()
    first = PostgresConnection(locks)
    second = PostgresConnection(locks)

    assert ScheduledRetentionCycle._acquire_lock(first) is True
    assert ScheduledRetentionCycle._acquire_lock(second) is False
    ScheduledRetentionCycle._release_lock(first)
    assert ScheduledRetentionCycle._acquire_lock(second) is True

    assert "pg_try_advisory_lock" in first.calls[0]
    assert "pg_advisory_unlock" in first.calls[1]


def test_retention_cycle_persists_purge_after_lock_transaction(monkeypatch) -> None:
    with TemporaryDirectory() as directory:
        sessions = build_session_factory(f"sqlite:///{directory}/talentflow.db")
        Base.metadata.create_all(sessions.kw["bind"])
        with sessions() as session:
            session.add_all(
                [
                    Tenant(id="tenant", name="Acme", slug="acme"),
                    User(id="admin"),
                    Requisition(
                        id="requisition",
                        tenant_id="tenant",
                        title="Engineer",
                        department="Engineering",
                        created_by="admin",
                    ),
                    CandidateCase(
                        id="candidate",
                        tenant_id="tenant",
                        requisition_id="requisition",
                        first_name="Avery",
                        last_name="Nguyen",
                        email="avery@example.test",
                        stage="rejected",
                        created_by="admin",
                        terminal_at=datetime.now(UTC) - timedelta(days=2),
                    ),
                    RetentionPolicy(tenant_id="tenant", retention_days=1),
                ]
            )
            session.commit()

        cycle = ScheduledRetentionCycle(
            sessions, schedule_seconds=60, batch_size=100, storage=directory
        )

        def acquire_with_transaction(connection) -> bool:
            connection.execute(text("SELECT 1"))
            return True

        monkeypatch.setattr(cycle, "_acquire_lock", acquire_with_transaction)

        assert cycle() == 1
        with sessions() as session:
            candidate = session.get(CandidateCase, "candidate")
            assert candidate is not None
            assert candidate.anonymized_at is not None
            assert candidate.email == "purged+candidate@redacted.invalid"
        sessions.kw["bind"].dispose()
