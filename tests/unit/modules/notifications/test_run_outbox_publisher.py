import subprocess
import sys


def test_standalone_relay_registers_all_foreign_key_targets():
    # Other suites import the API's complete registry and hide this startup failure.
    # A fresh interpreter must resolve the same FK dependency graph used by ORM flush.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
from app.modules.notifications.application import run_outbox_publisher
from app.shared.database import Base
names = {table.name for table in Base.metadata.sorted_tables}
assert {"outbox_events", "notification_deliveries", "tenants", "users"} <= names
print("registry ready")
""",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.stdout.strip() == "registry ready"
