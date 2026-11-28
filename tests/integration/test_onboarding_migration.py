import os
import subprocess
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text


def test_expand_upgrade_and_disposable_downgrade():
    url = os.getenv("ONBOARDING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("disposable PostgreSQL required")
    engine = create_engine(url)
    schema = "migration_" + uuid4().hex
    with engine.begin() as c:
        c.execute(text(f"CREATE SCHEMA {schema}"))
    env = {**os.environ, "DATABASE_URL": url, "PGOPTIONS": "-csearch_path=" + schema}

    def migrate(*args):
        result = subprocess.run(
            ["alembic", *args], env=env, capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, result.stderr

    try:
        migrate("upgrade", "d65a001")
        with engine.begin() as c:
            c.execute(text(f"SET LOCAL search_path TO {schema}"))
            c.execute(
                text(
                    "INSERT INTO tenants (id,name,slug,created_at) VALUES ('tenant','Keep','keep',now())"
                )
            )
        migrate("upgrade", "head")
        with engine.begin() as c:
            c.execute(text(f"SET LOCAL search_path TO {schema}"))
            assert c.scalar(text("SELECT name FROM tenants WHERE id='tenant'")) == "Keep"
            assert (
                c.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.columns WHERE table_schema=:schema AND table_name='candidate_cases' AND column_name='hire_start_date'"
                    ),
                    {"schema": schema},
                )
                == 1
            )
        migrate("downgrade", "d65a001")
        migrate("upgrade", "head")
    finally:
        with engine.begin() as c:
            c.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        engine.dispose()
