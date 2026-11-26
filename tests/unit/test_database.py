import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.shared.database import build_engine


def test_sql_errors_hide_bound_parameter_values():
    engine = build_engine("sqlite://")
    try:
        with engine.connect() as connection, pytest.raises(DBAPIError) as caught:
            connection.execute(
                text("SELECT * FROM missing_table WHERE name = :name"),
                {"name": "private-search@example.test"},
            )
        assert "private-search@example.test" not in str(caught.value)
        assert "SQL parameters hidden" in str(caught.value)
    finally:
        engine.dispose()
