from pathlib import Path

DOMAIN_ROOT = Path("app/modules")
FORBIDDEN = ("fastapi", "sqlalchemy", "pydantic", "sendgrid")


def test_domain_layer_does_not_depend_on_frameworks_or_infrastructure() -> None:
    violations: list[str] = []
    for path in DOMAIN_ROOT.glob("*/domain/**/*.py"):
        source = path.read_text()
        for dependency in FORBIDDEN:
            if f"import {dependency}" in source or f"from {dependency}" in source:
                violations.append(f"{path}: {dependency}")
    assert not violations, "Domain dependency violations: " + ", ".join(violations)
