# ADR-010: Feature flags — webhook release gate, delivery kill switch, evaluation context and lifecycle

- **Status:** Accepted
- **Date:** 2026-11-28
- **Issue:** DUTH-145 (parent DUTH-43); implemented by DUTH-65 (API, worker and web)
- **Amends:** [ADR-003](003-local-open-source-runtime-stack.md) (where flags are evaluated) and [ADR-008](008-outbound-webhooks.md) §5 (paused deliveries, auto-disable streak)

## Context

ADR 003 chose OpenFeature with flagd as the provider: flags are JSON in the repo, reviewed like code and hot-reloaded. It did not decide what is flagged, who evaluates, what the API returns when a feature is off, or how the system behaves when flagd is down. DUTH-65 is blocked on those decisions.

The first gated feature is **outbound webhooks** (ADR 008, built by DUTH-62 and DUTH-141). It needs two separate controls:

- a **release gate** that turns the whole feature on per tenant, and
- an **operational kill switch** that stops outbound HTTP for one tenant, or for every tenant, without losing events.

The machine-readable changes are:

- [`docs/feature-flags/openapi.yaml`](../feature-flags/openapi.yaml) (OpenAPI 3.1): `GET /v1/me` gains `features`, plus the `feature-disabled` problem.
- [`docs/feature-flags/webhooks-gate.overlay.yaml`](../feature-flags/webhooks-gate.overlay.yaml) ([OpenAPI Overlay 1.0](https://spec.openapis.org/overlay/v1.0.0.html)): the gate-off responses that DUTH-65 applies to `docs/webhooks/openapi.yaml`.

`docs/webhooks/openapi.yaml` is not edited in this PR. `tests/unit/test_webhook_security.py` compares that file with the routes FastAPI generates, so the gate-off responses must land together with the code that returns them. DUTH-65 applies the overlay, runs `scripts/sync_webhook_contract.py` and regenerates `web/openapi.json` in the same PR.

Constraints taken as given:

- Errors are RFC 9457 Problem Details ([`docs/api-errors.md`](../api-errors.md)).
- The authenticated actor comes from `resolve_actor` (`app/modules/identity/security.py`). Its `tenant_id` and `role` come from a verified token and a `Membership` row. `X-Tenant-Id` can only pick a tenant the principal is already a member of.
- Domain and application layers stay framework-free (`tests/architecture`). OpenFeature is an infrastructure dependency.
- flagd runs only inside Compose. Nothing outside the default Compose network may reach it.

## Options considered

**Where flags are evaluated.**

| Option | For | Against |
| --- | --- | --- |
| Browser OpenFeature web provider, talking to flagd (OFREP) | Instant UI updates | flagd would have to be exposed to the host. The client builds its own context, so a user could forge `tenant_id`. The browser and the API could disagree. **Rejected.** |
| Next.js BFF evaluates through its own server-side OpenFeature SDK | No API change | Two evaluation points that can disagree during a reload or an outage. A second network path to flagd. A second context builder to keep in sync. **Rejected.** |
| **The API evaluates. The web reads the result from `GET /v1/me`. The worker evaluates the same flags with a tenant-only context.** | One context builder and one fallback table. The API enforces, and the UI only reflects. flagd stays on the private network. | The UI reflects a change only on its next server render. Accepted, because the API is what enforces the gate (§4). |

**How the SDK reaches flagd.**

| Option | For | Against |
| --- | --- | --- |
| **RPC resolver, no client cache** | Every evaluation sees the latest flagd state. "flagd is unreachable" is a clear, testable condition that maps to the fallback. | One in-network gRPC call per evaluation. Fine at this volume: at most 2 per request, and the worker evaluates per tenant, not per delivery. |
| In-process resolver (syncs rules from flagd and evaluates locally) | Survives flagd outages using the last rules it synced | An outage is invisible until a process restarts, and then it suddenly falls back. Two failure modes to test instead of one. **Rejected for now.** Revisit if evaluation latency matters (it is a provider setting). |
| File resolver in each process | No flagd container at all | Contradicts ADR 003 (flagd in Compose). Every container would need the file mounted. **Used only in tests** (§8). |

**API status when the gate is off.**

| Option | Against |
| --- | --- |
| 404 `not-found` | It conflates with the tenant-isolation 404 from ADR 008, so the web cannot tell "feature off" from "endpoint gone". **Rejected.** |
| 409 `conflict` | Nothing is wrong with the resource state. **Rejected.** |
| **403 with a distinct type, `feature-disabled`** | Chosen. The admin knows the feature exists. The type tells clients what to show, and it is different from the permission failure `forbidden`. |

**What "off" does to pending deliveries.** If the gate reused ADR 008's endpoint disable, it would **cancel** pending deliveries and lose events on a rollback. If deliveries stayed claimable and failed, they would burn retry attempts and dead-letter. Both are rejected. The worker **pauses** instead: it does not claim the rows (§5).

## Decision

### 1. Flags and naming

**Naming convention for every flag:** `<kind>.<module>.<capability>`.

- `kind` is one of:
  - `release`: a temporary gate for a new feature. It must expire (§7).
  - `ops`: a permanent operational control such as a kill switch.
- `module` is the bounded-context directory under `app/modules/`, for example `webhooks`.
- `capability` is lowercase kebab-case.
- Regex: `^(release|ops)\.[a-z]+\.[a-z0-9]+(-[a-z0-9]+)*$`. A new kind needs an amendment to this ADR.
- Boolean flags are always **positive**: `true` means the capability runs. There are no `disable-*` flags, so nobody has to reason through a double negative while turning something off under pressure.
- A flag key is internal and never appears in an API response. The API exposes stable public feature names instead (§4), so a flag can be renamed or removed without a contract change.

**The two flags:**

| Key | Type | Variants | Default variant in the flag file | Code fallback (§6) | Context scope |
| --- | --- | --- | --- | --- | --- |
| `release.webhooks.outbound` | boolean | `on: true`, `off: false` | `off`. Targeting turns it `on` for the listed tenants. | `false` (fail-closed) | `tenant` |
| `ops.webhooks.delivery` | boolean | `on: true`, `off: false` | `on`. Targeting turns it `off` for the listed tenants. | `false` (fail-closed: pause) | `tenant` |

The **effective** states, used by the API, `/v1/me` and the worker alike, come from two pure functions in the application layer:

```text
webhooks_enabled(tenant)          = release.webhooks.outbound(tenant)
webhook_delivery_allowed(tenant)  = release.webhooks.outbound(tenant) AND ops.webhooks.delivery(tenant)
```

Gate on and kill switch off means "management works, delivery is paused". Gate off means delivery is paused as well.

**Flag file.** The file is `flags/talentflow.flagd.json` at the repo root, mounted read-only into flagd. Its initial content enables the seed tenant (`scripts/seed_demo.py`), so the current demo, E2E and DUTH-141 screens keep working:

```json
{
  "$schema": "https://flagd.dev/schema/v0/flags.json",
  "flags": {
    "release.webhooks.outbound": {
      "state": "ENABLED",
      "variants": {"on": true, "off": false},
      "defaultVariant": "off",
      "targeting": {
        "if": [{"in": [{"var": "tenant_id"}, ["00000000-0000-4000-8000-000000000001"]]}, "on", null]
      },
      "metadata": {
        "kind": "release", "owner": "backend", "issue": "DUTH-65",
        "contextScope": "tenant", "createdAt": "2026-11-28", "expiresAt": "2027-02-26"
      }
    },
    "ops.webhooks.delivery": {
      "state": "ENABLED",
      "variants": {"on": true, "off": false},
      "defaultVariant": "on",
      "targeting": {
        "if": [{"in": [{"var": "tenant_id"}, []]}, "off", null]
      },
      "metadata": {
        "kind": "ops", "owner": "backend", "issue": "DUTH-65", "contextScope": "tenant", "createdAt": "2026-11-28"
      }
    }
  }
}
```

Targeting only names the **exceptions**. Its else branch is always `null`, and flagd falls back to `defaultVariant` when targeting returns `null`. So `defaultVariant` is the value for every unlisted tenant, and changing it really changes every unlisted tenant. A hard-coded else branch such as `"on"` would silently ignore a `defaultVariant` edit; lint rule 8 (§7) forbids it.

- To pause one tenant, add its id to the `ops.webhooks.delivery` list.
- To pause **every** tenant, set its `defaultVariant` to `off`. Listed and unlisted tenants are then all `off`.
- Emergency alternative: `"state": "DISABLED"` makes every evaluation return the code fallback `false`, which also pauses everything.

Each is a one-line, reviewed change that flagd reloads without a restart. Targeting lists hold opaque tenant UUIDs only, never tenant names or other customer identifiers, because the file is committed to a public repository. **Percentage rollout (release flags only).** A `release` flag may replace its `null` else branch with flagd's `fractional` operator, in exactly this shape:

```json
{"if": [{"in": [{"var": "tenant_id"}, [<tenant ids>]]}, "on", {"fractional": [["on", N], ["off", 100 - N]]}]}
```

`fractional` buckets on `targetingKey`, which is the tenant id, so a tenant stays in the same bucket as `N` grows. Listed tenants stay `on`. While this shape is in place, `defaultVariant` does not apply to unlisted tenants. A release rollback is therefore the one-line change of the else branch back to `null`, with `defaultVariant: off`. `ops` flags **never** use `fractional`: their else branch is always `null`, so the `defaultVariant` global stop always reaches every tenant.

**Code side.** One registry module defines each flag once, with its key, fallback and scope. The application layer depends on a `FeatureFlags` port (`is_enabled(flag, context) -> bool`), and the OpenFeature adapter implements it in infrastructure. No other module imports `openfeature`, and an architecture test enforces this. No code passes a flag key as a string literal.

### 2. Evaluation context

The context is built in exactly one place per runtime, from trusted data only:

| Attribute | Source | Request scope (API) | Tenant scope (worker, and every flag with `contextScope: tenant`) |
| --- | --- | --- | --- |
| `targetingKey` | `ActorContext.tenant_id` / `webhook_deliveries.tenant_id` | yes | yes |
| `tenant_id` | same as above | yes | yes |
| `role` | `ActorContext.role` (one of the five roles in `CurrentActorResponse`) | yes | **absent** |

Rules:

- **No client-supplied targeting.** The builder reads only `ActorContext`. Query parameters, body fields and headers never reach the context, and there is no override header or cookie. `X-Tenant-Id` counts only through the membership check `resolve_actor` already does.
- **Nothing else goes in the context:** no user id, email, name, IP or user agent. Targeting individual users is out of scope. It would need a new ADR and a PII review.
- **Attribute names are snake_case without dots.** In JsonLogic, `{"var": "a.b"}` is a nested path.
- **A `tenant`-scope flag must not target on `role`.** The worker has no role, so a role rule would make the API and the worker disagree. Both webhook flags are `tenant` scope. `role` is reserved for future `request`-scope flags that only the API evaluates. The flag-file lint (§7) enforces this rule.
- **flagd stays inside the Compose network.** The `flagd` service:
  - joins the `default` network only, not `webhook-demo`, where the untrusted demo receiver lives;
  - publishes **no `ports:`**;
  - runs as a non-root user with the flag directory mounted read-only;
  - logs at `info`, so evaluation contexts are never written to its log.

  The API and `webhook-worker` reach it at `flagd:8013`. The web container has no flagd configuration, and an ESLint rule bans `@openfeature/*` imports under `web/`.
- **Environment variables** (names only; none is a secret): `FEATURE_FLAGS_PROVIDER` (`flagd` or `file`; tests use `file`), `FLAGD_HOST`, `FLAGD_PORT`, `FLAGD_RESOLVER` (`rpc`), `FLAGD_DEADLINE_MS` (`200`), `FLAGD_TLS` (`false`, in-network only), `FLAGD_CACHE` (`disabled`), and `FLAGD_OFFLINE_FLAG_SOURCE_PATH` (file mode only). DUTH-65 maps these onto `Settings` and checks the provider-specific names against the pinned provider version. It also pins the flagd image by digest, like the other images.

### 3. API behavior when the gate is off

**Precedence:** 401 `unauthorized` → 403 `forbidden` (missing `webhook:manage`) → **403 `feature-disabled`** → everything else (400, 404, 409, 412, 428). So a recruiter still gets `forbidden`. The one exception is PATCH: its gate needs the parsed body, so a PATCH body that fails model validation gets 422 `validation-error` first, whatever the gate state. The gate check runs before idempotency handling. Only 2xx responses are stored (ADR 005), so a retry after the gate opens runs normally.

| Operation | Gate off |
| --- | --- |
| `GET /v1/webhook-event-types` | allowed |
| `GET /v1/webhook-endpoints`, `GET /v1/webhook-endpoints/{id}` | allowed |
| `GET /v1/webhook-endpoints/{id}/deliveries`, `GET /v1/webhook-deliveries/{id}` | allowed |
| `PATCH /v1/webhook-endpoints/{id}` with a JSON body that is **exactly** `{"enabled": false}` | allowed. ADR 008 behavior is unchanged: `disabled_reason = manual` and pending deliveries are **cancelled**, which is the admin's explicit choice. |
| `PATCH` with any other body (re-enable, URL, description, event types, or `enabled:false` combined with another field) | **403 `feature-disabled`**. The check compares the **parsed** request model, `model_dump(exclude_unset=True) == {"enabled": False}`, so the gate and the handler can never read the body differently (duplicate keys, `0` for `false`). |
| `DELETE /v1/webhook-endpoints/{id}` | allowed |
| `POST /v1/webhook-endpoints/{id}/secret-rotations` | allowed. It is a containment action for a leaked secret, and nothing is signed while delivery is paused. |
| `POST /v1/webhook-endpoints` (create) | **403 `feature-disabled`** |
| `POST /v1/webhook-deliveries/{id}/redeliveries` | **403 `feature-disabled`** |

Every webhook operation still requires `If-Match`, `Idempotency-Key` and its other ADR 008 rules exactly as today. The kill switch has **no** API effect: with the gate on and delivery off, every operation works, and a redelivery creates a `pending` row that stays paused.

**Problem body:**

```json
{
  "type": "https://github.com/duthaho/talentflow/blob/main/docs/api-errors.md#feature-disabled",
  "title": "Feature Disabled",
  "status": 403,
  "detail": "Webhooks are not enabled for this organization. Existing endpoints can still be viewed, disabled, rotated or deleted.",
  "instance": "/v1/webhook-endpoints",
  "correlation_id": "…",
  "feature": "webhooks"
}
```

`feature` is the public feature name from `/v1/me`. The body is identical whether the flag evaluated to `off` or fell back because flagd was down, and it never carries the flag key, variant or reason. The response sets `Cache-Control: no-store`.

**Fan-out is not gated.** The `webhooks` consumer (ADR 006 / ADR 008 §5) evaluates no flags and keeps creating `pending` rows for **enabled** endpoints. A rollback of the gate therefore loses no events. A tenant that has never been enabled has no endpoints, so it gets no rows.

### 4. Web behavior

- **Source of truth.** `GET /v1/me` gains a required `features` object, evaluated in the caller's request context:

  ```json
  "features": {"webhooks": {"enabled": true, "delivery_paused": false}}
  ```

  `enabled` is `webhooks_enabled(tenant)`. `delivery_paused` is `NOT webhook_delivery_allowed(tenant)`. When flagd is down, `/v1/me` still returns 200 with the fallback values (`false` / `true`). Flag problems never fail `/v1/me`. The schema is in `docs/feature-flags/openapi.yaml`. Every caller gets `features`; it is tenant state, not a secret.
- `toActor` (`web/src/lib/actor/current-actor.ts`) maps it to `actor.features.webhooks.{enabled, deliveryPaused}`. The web never calls flagd and never decides a flag on its own.
- **Navigation.** The "Webhooks" item shows only with `webhook:manage` **and** `enabled`.
- **`/settings/webhooks` when `enabled` is false.** The page still renders for `webhook:manage`, so an admin can reach existing endpoints through the URL after a rollback:
  - a neutral notice: "Webhooks are turned off for your organization. You can still view, disable, rotate or delete existing endpoints. Events for enabled endpoints are kept and sent if webhooks are turned back on."
  - the endpoint list and the delivery log are **read-only**. Only Disable, Rotate secret and Delete are offered. Create, Edit, Re-enable and Redeliver are not rendered.
  - with no endpoints, the page shows the empty state "Webhooks are not available for your organization yet."
- **`enabled` and `delivery_paused` both true:** a warning banner above the workspace: "Delivery is paused for your organization. Pending deliveries are kept and will be sent when delivery resumes; waiting does not use up retry attempts."
- **Mid-session change.** If a mutation returns 403 `feature-disabled`, the UI shows the disabled notice in place of the form error and calls `router.refresh()`, so the server re-renders with a fresh `/v1/me`.
- **How quickly a toggle reaches an open session.** There is no polling or push. flagd reloads the file within ~1 s of the save (file watch). The API sees the new value on its **next request**, because there is no client cache. The web reflects it on the **next server render**: any navigation, a refresh, or the `router.refresh()` above. `getCurrentActor` is cached per render only. Enforcement never depends on the UI. The contract the tests assert: a saved file change is enforced by the API **within 5 s**.

### 5. Worker behavior

The kill switch and the gate are evaluated **per tenant, without a role**, using the tenant-scope context from §2. ADR 008 §5 is amended as follows:

1. **Snapshot.** Before claiming, the worker reads the distinct `tenant_id`s that have `pending` deliveries, using the partial index `ix_webhook_deliveries_due`. It evaluates `webhook_delivery_allowed` once per tenant and keeps the allowed set. The snapshot is rebuilt before a claim whenever it is older than **5 s**, so a long cycle cannot act on stale flags.
2. **Paused rows are never claimed.** `claim()` adds `webhook_deliveries.tenant_id IN (<allowed>)` to both queries (and `webhook_endpoints.tenant_id IN (<allowed>)` to the endpoint query). A paused row is never leased, so `status`, `attempt_count`, `next_attempt_at` and `leased_until` stay exactly as they were. **No new delivery status, and no change to existing rows.** A paused delivery shows as `pending` in the log, and the banner in §4 explains why.
3. **In-flight attempts finish.** An attempt claimed before the flip runs to completion, bounded by the 10 s attempt deadline from ADR 008 §4. This matches how ADR 008 handles a URL change.
4. **Resume.** When a tenant is allowed again, its overdue rows are claimed in `next_attempt_at` order. The existing per-endpoint limit (4 in flight) throttles the backlog. The backoff schedule continues from the stored `attempt_count`, and no attempt is consumed by the pause.
5. **Pause bookkeeping, and the auto-disable streak.** Without a correction, paused time would count toward ADR 008's 72 h streak age, and the first failure after a long pause could disable a healthy endpoint. One expand-only table records pauses:

   ```sql
   CREATE TABLE webhook_delivery_pauses (
     tenant_id     varchar(36)  PRIMARY KEY,
     paused_since  timestamptz  NOT NULL,
     reason        varchar(16)  NOT NULL CHECK (reason IN ('flag_off', 'flag_error'))
   );
   ```

   - The tenant is in the snapshot but not allowed: `INSERT … ON CONFLICT (tenant_id) DO UPDATE SET reason = EXCLUDED.reason`. `paused_since` keeps its first value.
   - The tenant is allowed again: in **one transaction**, `DELETE FROM webhook_delivery_pauses WHERE tenant_id = :t RETURNING paused_since`. If a row came back, the transaction also runs `UPDATE webhook_endpoints SET failure_streak_started_at = failure_streak_started_at + (now() - :paused_since) WHERE tenant_id = :t AND failure_streak_started_at IS NOT NULL`. `DELETE … RETURNING` succeeds for only one replica, so the shift is applied exactly once.
   - `reason = flag_error` means the flags fell back because flagd was unreachable. `flag_off` means a flag really evaluated to `off`.
   - A tenant that has a pause row but is no longer in the snapshot (for example, an admin cancelled all its pending deliveries during the pause) is treated as resumed: the same `DELETE … RETURNING` and shift run. So a row exists only while its tenant has pending deliveries and is paused.
   - The table holds no PII and needs no retention rule.
6. **Retention.** Paused rows are `pending`, not terminal, so the 30-day purge (ADR 008 §5) never touches them, nor the `webhook_events` they reference. Events are kept for as long as the pause lasts. To discard them, an admin disables or deletes the endpoint, which cancels its pending deliveries (allowed even with the gate off, §3).
7. **Worker loop.** `pending_count()` keeps counting paused rows, so the loop polls at `WORKER_POLL_SECONDS` while a backlog exists. That poll interval bounds how quickly a resume is noticed.
8. **No flags in the consumer**, as stated in §3.

The outcome confirms the behavior the issue asked for: when a flag is off or flagd is unavailable, pending deliveries are **paused, not sent, not dropped**, consume **no** retry attempts, and resume on recovery.

### 6. Defaults, outage, timeouts, caching and telemetry

**Fallbacks.** The code fallback is what OpenFeature returns on any error: flagd unreachable, deadline exceeded, provider not ready, `FLAG_NOT_FOUND`, `TYPE_MISMATCH`, a parse error, or a flag with `state: DISABLED`.

| Flag | Fallback | Effect during a flagd outage |
| --- | --- | --- |
| `release.webhooks.outbound` | `false` (fail-closed) | Create, re-enable and redeliver return 403. Reads, disable, rotate and delete keep working. |
| `ops.webhooks.delivery` | `false` (fail-closed) | Every tenant's deliveries pause (`reason = flag_error`) and resume when flagd is back. |

Both fail closed because the failure is reversible: nothing is lost or retried away, and outbound data never leaves without an explicit `on`. A future flag picks its fallback by asking which state is safe to stay in for an unknown time. Its PR says why. Every flag's code fallback is its `off` variant, `false`, and lint rule 7 checks this. The file's `defaultVariant` may move to `on` during rollout (§7); the fallback does not. So a fully rolled-out release flag still turns its feature off during a flagd outage, until the flag is retired.

**Timeout.** Each evaluation has a **200 ms** deadline (`FLAGD_DEADLINE_MS`). The provider does not retry. The SDK reconnects in the background. A request makes at most 2 evaluations, so flags add at most 400 ms in the worst case. Startup does **not** wait for flagd: `/health/ready` of the API and workers does not depend on it, and an unready provider simply returns the fallback.

**Caching.** There is no client-side cache in the API (`FLAGD_CACHE=disabled`). The worker keeps only the snapshot from §5, which is at most 5 s old. The web keeps only the per-render `getCurrentActor` cache.

**Telemetry.** An OpenFeature hook in the adapter records:

- **Span event** `feature_flag.evaluation` on the current span, using the OpenTelemetry feature-flag semantic conventions: `feature_flag.key`, `feature_flag.result.variant`, `feature_flag.result.reason`, `feature_flag.provider.name`, and `error.type` on error. Evaluation-context attributes are **not** recorded.
- **Metric** `talentflow_feature_flag_evaluations_total{flag_key, variant, reason}`. There is no tenant label (cardinality). The worker adds gauges `talentflow_webhook_delivery_paused_tenants` and `talentflow_webhook_deliveries_paused` (the pending rows of paused tenants).
- **Logs.** A WARN `feature_flag_evaluation_failed` with `flag_key`, `error_code` and `reason`, at most once per flag per 60 s per process, so an outage does not flood the logs. The worker logs INFO `webhook_delivery_paused` / `webhook_delivery_resumed` with `tenant_id` (an opaque internal id, already present in worker logs) and `reason`, once per transition per process.
- **Never logged or traced:** the evaluation context, user ids, emails, names, tokens, `Authorization`, webhook URLs and secrets. The OTel Collector's attribute scrubbing stays the backstop.

### 7. Lifecycle: create → rollout → remove

| Step | What happens | Gate |
| --- | --- | --- |
| **Create** | One PR adds the flag to `flags/talentflow.flagd.json` with metadata, its registry entry (key, fallback, scope), the checks in code, and tests for both values and the fallback. The file starts at the safe value. | Code review. Hoàng-Security reviews flags that gate data leaving the system or authorization. |
| **Roll out** | Each step is a reviewed one-line PR: tenant list (else `null`) → optional `fractional` else branch in the §1 shape, raising `N` → `defaultVariant: on` with no targeting. flagd hot-reloads every step. | Code review |
| **Remove (release only)** | (1) The flag is fully on everywhere for **at least 7 days**: `defaultVariant: on`, no `targeting`. (2) **PR A** deletes every check and marks the registry entry `retired=True`. A retired entry cannot be evaluated: `is_enabled` raises, and nothing in code references it. Public fields stay (for example `features.webhooks.enabled` becomes a constant `true`), so the API contract does not change. (3) **After** PR A is merged, **PR B** deletes the file entry and the retired registry entry together. | The order matters: if the file entry goes first, evaluations hit `FLAG_NOT_FOUND`, return the fail-closed fallback, and switch the feature **off**. The registry and file key sets stay equal at every step (rule 5). |
| **Kill switch (`ops`)** | Permanent. It has no `expiresAt`. Its owner reviews it whenever the module's ADR changes. | — |

**Ownership.** `metadata.owner` names the team role (`backend`, `frontend`, `platform`) that answers for the flag. `metadata.issue` names the issue that introduced it.

**Stale-flag rule (covers DUTH-65 AC4).** `release` flags must set `expiresAt` no more than **90 days** after `createdAt`. Once `expiresAt` has passed, the lint fails. This red build on the expiry date is intentional: the owner either removes the flag or extends it in a PR that gives the reason. It is the only reminder mechanism, and it needs no extra infrastructure.

**Flag-file lint** (`tests/unit/test_feature_flags_file.py`, part of DUTH-65). It checks that:

1. the file validates against the flagd JSON schema;
2. every key matches the naming regex;
3. the required metadata is present (`kind`, `owner`, `issue`, `contextScope`, `createdAt`, plus `expiresAt` for `release` flags);
4. no `release` flag has expired, and none expires more than 90 days after creation;
5. the keys in the file and the keys in the code registry (retired entries included) are the same set. A key in only one place fails, which catches half-finished removals;
6. `contextScope: tenant` flags contain no `{"var": "role"}` in their targeting;
7. every flag has exactly the variants `on: true` and `off: false`, and its code fallback is `false`. `defaultVariant` may be `on` or `off`;
8. `targeting`, when present, is one `if` over a `tenant_id` list. Its then branch is a fixed value per kind, independent of `defaultVariant`: `"off"` for `ops` flags (a listed tenant is always paused, even while `defaultVariant` is `off` for a global stop) and `"on"` for `release` flags (a listed tenant is always enabled). Its else branch is `null`, so `defaultVariant` decides for every unlisted tenant. The single exception: a `release` flag with `defaultVariant: off` may use, as the else branch, the §1 `fractional` shape with exactly the buckets `on` and `off`, integer weights summing to 100. Any `fractional` in an `ops` flag fails;
9. a `retired` registry entry is fully on in the file (`defaultVariant: on`, no `targeting`), and no code outside the registry references it (an AST check).

### 8. Test matrix DUTH-65 must cover (AC2)

Integration tests use `FEATURE_FLAGS_PROVIDER=file`, the real flagd JsonLogic evaluator in-process, with a temporary flag file. Hot-reload and outage tests run against the real `flagd` container in the Compose-based E2E job (`docker-compose.e2e.yml`).

| # | Area | Scenario | Expected |
| --- | --- | --- | --- |
| T1 | Tenant isolation | Gate on for tenant A, off for tenant B | A: create 201, `/v1/me` `enabled: true`, deliveries sent. B: create 403 `feature-disabled`, `enabled: false`, deliveries stay `pending` with an unchanged `attempt_count`. |
| T2 | Role isolation | Same tenant, `tenant_admin` vs `recruiter`; plus a test-only `request`-scope flag that targets `role` | A recruiter gets 403 `forbidden`, not `feature-disabled`. The `release.webhooks.outbound` result is the same for every role. The request-scope test flag differs by role. |
| T3 | No client targeting | Send `?tenant_id=`, body fields, `X-Feature-*` headers, and an `X-Tenant-Id` the principal is not a member of | The context key set is exactly `{targetingKey, tenant_id, role}` in the API and `{targetingKey, tenant_id}` in the worker. The foreign `X-Tenant-Id` gets the existing 403. The evaluation result does not change. |
| T4 | Gate-off route matrix | Every row of the §3 table, including `PATCH {"enabled": false}`, `{"enabled": false, "description": "x"}`, `{"enabled": true}`, the duplicate-key raw body `{"enabled": true, "enabled": false}` and `{"enabled": 0}` | Statuses as in §3. The duplicate-key body and `{"enabled": 0}` are decided on the parsed model, so the gate allows exactly the bodies the handler applies as a disable, and blocks the rest. Allowed disable/delete cancel pending deliveries (ADR 008). A 403 is not stored under its `Idempotency-Key`. |
| T5 | Kill switch | Gate on, `ops.webhooks.delivery` off for tenant A | Every API operation works. Redeliver creates a paused `pending` row. A's rows are not claimed. Tenant B keeps delivering. A pause row exists with `reason = flag_off`. **Global stop:** with an empty tenant list and `defaultVariant: off`, every tenant pauses, including tenants that were never listed. The same holds for `"state": "DISABLED"`. Setting `defaultVariant` back to `on` resumes them all. |
| T6 | Hot reload | In the running stack, edit the mounted flag file (gate off → on; delivery on → off → on for one listed tenant; then the global stop: `ops.webhooks.delivery` `defaultVariant` on → off → on with an unlisted tenant B) | The API enforces the new value within 5 s. The worker pauses or resumes within 5 s + `WORKER_POLL_SECONDS` + 10 s in flight. During the global stop, unlisted tenant B pauses and its `/v1/me` shows `delivery_paused: true`. After a reload, `/settings/webhooks` shows the matching state. |
| T7 | flagd outage | Stop flagd, or point the provider at a closed port | Each evaluation returns the fallback in under 300 ms. `/v1/me` returns 200 with `enabled: false, delivery_paused: true`. Reads, disable, rotate and delete keep working, and create returns 403. Worker rows stay unchanged, with a pause row `reason = flag_error`. `/health/ready` stays green. One rate-limited WARN appears. |
| T8 | Recovery | Start flagd again after T7 | Deliveries are sent in `next_attempt_at` order. Each delivery's `attempt_count` grows by exactly 1 per real attempt. `failure_streak_started_at` is shifted by the paused duration. With two workers racing on resume, the shift is applied exactly once. |
| T9 | Streak | An endpoint with 19 failures over 70 h, then a 3-day pause, then one failure | The endpoint is **not** auto-disabled (the streak age excludes the pause). Control: the same history with the pause counted (the §5.5 shift skipped) **is** disabled, because the streak is then older than 72 h. A stale pause row for a tenant with no pending deliveries is deleted on the next snapshot. |
| T10 | Agreement | A table-driven test over {gate on/off} × {delivery on/off} × {flagd up/down} | For every cell: API create allowed ⇔ `features.webhooks.enabled`; worker delivers ⇔ `NOT features.webhooks.delivery_paused`. The web shows the state that `/v1/me` returned (component tests: nav visibility, read-only disabled page, paused banner, `router.refresh()` on 403). |
| T11 | Telemetry hygiene | Capture spans, metrics and logs during T1, T7 and T8 | Only the allowed attributes from §6 appear. No email, user id, token, URL or evaluation context. |
| T12 | Lifecycle lint | The nine lint rules in §7, each with a failing fixture (including a hard-coded else branch such as `"on"`, an `ops` then branch of `"on"` (which would exempt listed tenants from the global stop), a `release` then branch of `"off"`, a `fractional` in an `ops` flag, a `fractional` whose weights don't sum to 100 or that names a third bucket, and a retired entry still referenced in code). Plus passing fixtures for every lifecycle and operating stage: a new release flag (`defaultVariant: off`, tenant list); the `ops` global stop with an empty tenant list (`defaultVariant: off`, then branch `"off"`); the global stop with a non-empty tenant list (same, with tenants listed); the restore after a global stop (`defaultVariant: on`, list unchanged); a percentage rollout (the §1 `fractional` else branch, for example `N = 25`); a fully rolled-out flag (`defaultVariant: on`, fallback `false`); after removal PR A (retired registry entry, file fully on); and after PR B (both gone). | Each failing fixture fails with a message that names the flag and the rule. Every lifecycle-stage fixture passes, so following §7 never turns the build red; the only intended red build is the expiry in rule 4. |

## Consequences

- One evaluation path, the API plus the worker with the same tenant context, keeps the API, the web and the worker in agreement by construction. The web gives up instant UI updates; the API still enforces immediately.
- A flagd outage degrades webhooks safely: no data leaves, nothing is lost, and nothing is retried away. Everything else in the product is unaffected, because no other flags exist yet. Each future flag must choose its fallback deliberately.
- DUTH-65 adds one table (`webhook_delivery_pauses`, expand-only) and one Compose service. It changes no existing column.
- A long pause grows the pending backlog without bound. The gauges in §6 make that visible. The remedy is the admin's disable or delete, which cancels pending deliveries.
- Every flag PR is a reviewed diff in Git (ADR 003). There is no toggle UI and no audit trail beyond Git history. That is acceptable for a local showcase. Unleash remains the documented alternative.

## Rollout (DUTH-65, one PR)

1. Expand-only Alembic revision for `webhook_delivery_pauses`.
2. Flag registry, port, OpenFeature adapter and hook. Add the `flagd` Compose service (no ports, `default` network only) and `flags/talentflow.flagd.json` with the seed tenant enabled.
3. API gate (§3). Apply the overlay to `docs/webhooks/openapi.yaml`, run `scripts/sync_webhook_contract.py`, and add `feature-disabled` to the problem registry.
4. `/v1/me` `features`, then regenerate `web/openapi.json` and `web/src/lib/api/schema.ts`.
5. Worker snapshot, claim filter and pause bookkeeping (§5).
6. Web: actor mapping, nav, disabled and paused states (§4).
7. The tests in §8. Then update the README pattern-catalog row for DUTH-65 to `implemented`.

**Rollback.** Set `release.webhooks.outbound` `defaultVariant` to `on` with no targeting, which restores today's behavior for every tenant, and remove the gate code in a follow-up. The pause table can stay, because it is empty when nothing is paused.

## Open questions

None block DUTH-65. One follow-up is outside this contract: emailing tenant admins when their delivery is paused for more than 24 h. It belongs with the ADR 008 auto-disable email follow-up (owner: Phương-CTO, to schedule).
