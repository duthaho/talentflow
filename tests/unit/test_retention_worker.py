from types import SimpleNamespace

from app.workers.retention import ScheduledRetentionCycle


class PostgresSession:
    def __init__(self) -> None:
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        self.calls: list[str] = []

    def scalar(self, statement, params):
        self.calls.append(str(statement))
        assert params == {"name": "talentflow:retention"}
        return True

    def execute(self, statement, params):
        self.calls.append(str(statement))
        assert params == {"name": "talentflow:retention"}


def test_retention_uses_and_releases_postgres_advisory_lock() -> None:
    session = PostgresSession()

    assert ScheduledRetentionCycle._acquire_lock(session) is True
    ScheduledRetentionCycle._release_lock(session)

    assert "pg_try_advisory_lock" in session.calls[0]
    assert "pg_advisory_unlock" in session.calls[1]
