# TalentFlow

A production-oriented, multi-tenant HR candidate workflow and case-management platform.

## Phase 1 delivered

- Modular FastAPI foundation with explicit `identity`, `tenancy`, `audit`, `requisitions`, and `candidates` modules.
- Tenant-scoped RBAC and request identity context.
- Candidate-case creation validates tenant-owned requisitions and enforces normalized, tenant-unique emails.
- Explicit candidate state machine, authorization-gated stage transitions, and database-level optimistic locking.
- Transactional audit records for tenant bootstrap, requisition, and candidate-case creation.
- PostgreSQL-ready configuration, Docker Compose local environment, health endpoint, test and lint gates.

## Run locally

```bash
uv sync --all-groups
uv run uvicorn app.main:app --reload
```

Run the tests:

```bash
uv run pytest
uv run ruff check .
```

Run with PostgreSQL:

```bash
docker compose up --build
```

## Architecture

The application starts as a modular monolith. Modules own their domain types and persistence models; API handlers orchestrate commands but do not contain authorization or business policy. The next phases add candidate lifecycle, interview feedback, offer approvals, transactional outbox, and reporting projections.
