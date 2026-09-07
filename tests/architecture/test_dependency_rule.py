from pathlib import Path

DOMAIN_ROOT = Path("app/modules")
FORBIDDEN = ("fastapi", "sqlalchemy", "pydantic", "sendgrid")
APPLICATION_FORBIDDEN = ("fastapi", "sqlalchemy", "pydantic", "sendgrid", "app.shared.models")
CLEAN_ARCHITECTURE_MODULES = ("candidates", "offers")


def test_domain_layer_does_not_depend_on_frameworks_or_infrastructure() -> None:
    violations: list[str] = []
    for path in DOMAIN_ROOT.glob("*/domain/**/*.py"):
        source = path.read_text()
        for dependency in FORBIDDEN:
            if f"import {dependency}" in source or f"from {dependency}" in source:
                violations.append(f"{path}: {dependency}")
    assert not violations, "Domain dependency violations: " + ", ".join(violations)


def test_application_layer_depends_on_ports_not_frameworks() -> None:
    violations: list[str] = []
    for module in CLEAN_ARCHITECTURE_MODULES:
        for path in (DOMAIN_ROOT / module / "application").glob("**/*.py"):
            source = path.read_text()
            for dependency in APPLICATION_FORBIDDEN:
                if f"import {dependency}" in source or f"from {dependency}" in source:
                    violations.append(f"{path}: {dependency}")
    assert not violations, "Application dependency violations: " + ", ".join(violations)
