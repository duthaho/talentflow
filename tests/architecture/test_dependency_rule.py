import re
from pathlib import Path

DOMAIN_ROOT = Path("app/modules")
FORBIDDEN = ("fastapi", "sqlalchemy", "pydantic", "sendgrid")
APPLICATION_FORBIDDEN = ("fastapi", "sqlalchemy", "pydantic", "sendgrid", "app.shared.models")
CLEAN_ARCHITECTURE_MODULES = (
    "attachments",
    "audit",
    "calendar",
    "candidates",
    "interviews",
    "offers",
    "organization",
    "reporting",
    "retention",
    "webhooks",
    "feature_flags",
)
ALLOWED_CROSS_CONTEXT_PERSISTENCE_IMPORTS = {
    ("candidates", "retention"): "public consent reads the tenant retention period",
    ("webhooks", "notifications"): "webhook fanout shares the broker inbox transaction",
    ("webhooks", "audit"): "webhook lifecycle writes tenant-scoped audit in the transaction",
    ("webhooks", "organization"): "tenant row serializes endpoint quota enforcement",
    ("audit", "candidates"): "case timeline checks that the case exists in the tenant (read only)",
    ("audit", "attachments"): "case timeline joins tenant-scoped attachment ids (read only)",
    ("attachments", "audit"): "attachment lifecycle writes an audit event in the same transaction",
    ("attachments", "candidates"): "attachment ownership is checked against the candidate record",
    ("calendar", "audit"): "calendar lifecycle writes an audit event in the same transaction",
    ("calendar", "interviews"): "calendar feed projects interviewer appointments",
    ("calendar", "organization"): "calendar subscriptions validate interviewer membership",
    ("candidates", "audit"): "candidate lifecycle writes an audit event in the same transaction",
    ("candidates", "organization"): "candidate creation validates a requisition",
    ("identity", "organization"): "authorization resolves the tenant membership record",
    ("interviews", "audit"): "interview lifecycle writes an audit event in the same transaction",
    ("interviews", "candidates"): "interview scheduling and reads validate candidate ownership",
    (
        "interviews",
        "organization",
    ): "interview scheduling and reads validate interviewer membership",
    ("notifications", "organization"): "email delivery resolves the recipient address",
    ("offers", "notifications"): "offer approval writes its transactional outbox event",
    (
        "organization",
        "audit",
    ): "organization lifecycle writes an audit event in the same transaction",
    ("reporting", "candidates"): "CQRS-lite reporting read model projects candidate state",
    ("reporting", "interviews"): "CQRS-lite reporting read model projects interview state",
    ("reporting", "offers"): "CQRS-lite reporting read model projects offer state",
    ("retention", "attachments"): "retention purge deletes candidate attachments",
    ("retention", "audit"): "retention lifecycle writes an audit event in the same transaction",
    ("retention", "candidates"): "retention purge selects terminal candidate cases",
}


def test_modules_do_not_reach_into_another_modules_infrastructure() -> None:
    violations: list[str] = []
    for path in DOMAIN_ROOT.glob("*/**/*.py"):
        owner = path.relative_to(DOMAIN_ROOT).parts[0]
        for line in path.read_text().splitlines():
            if (
                "app.modules." in line
                and ".infrastructure" in line
                and f"app.modules.{owner}." not in line
            ):
                violations.append(f"{path}: {line.strip()}")
    assert not violations, "Cross-module infrastructure imports: " + ", ".join(violations)


def test_modules_do_not_import_shared_model_exports() -> None:
    violations = [
        str(path)
        for path in DOMAIN_ROOT.glob("*/**/*.py")
        if "app.shared.models" in path.read_text()
    ]
    assert not violations, "Module records must use a context persistence interface: " + ", ".join(
        violations
    )


def test_cross_context_persistence_imports_are_explicitly_allowed() -> None:
    violations: list[str] = []
    pattern = re.compile(r"from app\.modules\.([a-z_]+)\.persistence import")
    for path in DOMAIN_ROOT.glob("*/**/*.py"):
        importer = path.relative_to(DOMAIN_ROOT).parts[0]
        for line in path.read_text().splitlines():
            match = pattern.match(line)
            if (
                match
                and match.group(1) != importer
                and (importer, match.group(1)) not in ALLOWED_CROSS_CONTEXT_PERSISTENCE_IMPORTS
            ):
                violations.append(f"{path}: {line.strip()}")
    assert not violations, "Unapproved cross-context persistence imports: " + ", ".join(violations)


def test_app_factory_only_composes_routers() -> None:
    source = Path("app/main.py").read_text()
    assert "@app." not in source


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


def test_public_routes_never_resolve_an_actor():
    from fastapi.routing import APIRoute

    from app.api.webhook_router import webhook_actor
    from app.main import create_app
    from app.modules.identity.security import resolve_actor

    def calls(dependency):
        return {dependency.call} | set().union(*(calls(d) for d in dependency.dependencies))

    def routes(router):
        for route in router.routes:
            if hasattr(route, "original_router"):
                yield from routes(route.original_router)
            else:
                yield route

    # Webhooks wrap resolve_actor to preserve their distinct 401/403 contract.
    authentication_guards = {resolve_actor, webhook_actor}
    checked = []
    for route in routes(create_app("sqlite://")):
        if not isinstance(route, APIRoute) or not route.path.startswith("/v1/"):
            continue
        checked.append(route.path)
        dependencies = calls(route.dependant)
        if route.path.startswith("/v1/public/"):
            assert authentication_guards.isdisjoint(dependencies), route.path
        # Existing bootstrap and bearer-capability feed are intentionally anonymous.
        elif route.path not in {"/v1/tenants", "/v1/calendar-feeds/{token}.ics"}:
            assert authentication_guards.intersection(dependencies), route.path

    assert len(checked) > 30
    assert sum(path.startswith("/v1/public/") for path in checked) == 3
