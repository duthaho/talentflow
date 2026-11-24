from types import SimpleNamespace

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
