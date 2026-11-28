# Operating feature flags

[ADR 010](../adr/010-feature-flags.md) defines the contract and lifecycle. The API is the
evaluation authority; the web reads `GET /v1/me`. Flags never grant permissions.

Run `docker compose up --build`: the API and webhook worker start flagd on the private
default network. There is no host port. `Dockerfile.flagd` pins the official runtime
by digest and adds a pinned static BusyBox binary solely for the `/readyz` probe.
Neither API nor worker readiness depends on flagd being reachable.

Edit `flags/talentflow.flagd.json` in a reviewed change. The **directory** is mounted
read-only, so both in-place writes and atomic editor saves are visible. No rebuild or
redeploy is needed. The seed tenant is initially enabled; other tenants are off.

- Enable a tenant: add its opaque UUID to the release flag's tenant list.
- Pause a tenant: add its UUID to the delivery flag's exception list.
- Pause everyone: set the delivery flag's `defaultVariant` to `off`. Listed tenants
  already target `off`; unlisted tenants now use that same value.
- Resume: restore the delivery default to `on` and remove any tenant exceptions
  that should resume. The release gate must also be on for that tenant.
- An unavailable provider fails closed. Existing endpoints remain readable and can
  be disabled, rotated or deleted. Disable/delete explicitly cancels pending rows;
  a flag pause preserves them without consuming retries. The consumer keeps fan-out
  running while delivery is paused.

The API observes edits within five seconds. The worker refreshes its tenant snapshot
after at most five seconds, then polls at `WORKER_POLL_SECONDS`; an already claimed
attempt finishes under its existing deadline. The web reflects state on its next
server render. There is no polling or browser provider.

Runtime setting names: `FEATURE_FLAGS_PROVIDER`, `FLAGD_HOST`, `FLAGD_PORT`,
`FLAGD_RESOLVER`, `FLAGD_DEADLINE_MS`, `FLAGD_TLS`, `FLAGD_CACHE`,
`FLAGD_OFFLINE_FLAG_SOURCE_PATH`. Defaults and targeting restrictions are in ADR 010.
File mode is for offline tests; runtime Compose selects uncached RPC explicitly.
The pinned Python provider maps settings onto `resolver_type`, `deadline_ms`,
`cache`, and `offline_flag_source_path`. Its implicit RPC retries are disabled in
the adapter. Initialization is asynchronous and shutdown joins its owned watchers.

Apply the expand-only pause table with `uv run --python 3.13 alembic upgrade head` on
your own local database. Its downgrade removes only `webhook_delivery_pauses`.
Resume uses transactional `DELETE RETURNING` to shift failure-streak timestamps
once across worker replicas. Paused rows remain pending and survive retention;
the backlog can grow while paused.

Validate locally:

```sh
uv run --python 3.13 python -m scripts.validate_feature_flags
uv run --python 3.13 python -m pytest
DUTH65_LIVE_FLAGS=1 uv run --python 3.13 python -m pytest tests/integration/test_feature_flags_live.py --no-cov
```

The last command creates a unique disposable Compose project with real flagd and
PostgreSQL, checks file reload, global stop, outage/recovery, migration up/down,
and two-worker resume fencing, then removes its containers and volumes. It publishes
test ports on loopback only. Other tests use the real offline flagd evaluator;
existing workflow fixtures explicitly enable both flags so those suites keep
testing their original behavior.

Telemetry: `feature_flag.evaluation` span events, bounded evaluation metrics,
rate-limited failure warnings, and pause/resume logs. The two worker gauges expose
paused tenant/delivery counts without tenant labels. Contexts, PII, URLs and secrets
are excluded from flag telemetry.

Before removing a release flag, follow ADR 010's two-PR sequence; deleting its file
entry before removing the checks switches the feature off. The lifecycle test runs
offline against the vendored flagd schemas and enforces expiry, registry agreement,
safe targeting, and retired-reference cleanup.
