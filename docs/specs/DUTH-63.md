# DUTH-63: Public careers page and candidate self-apply

## Context and problem

Every TalentFlow route today needs a Keycloak session. Candidates enter the system only when a recruiter creates them through `POST /v1/candidate-cases`. Stage 5 of DUTH-43 adds a public careers page per tenant where anyone can apply with a CV. That makes it the first anonymous, untrusted write path in the product, so it is the showcase for handling hostile input (`docs/roadmap.md`, stage 5).

State of `main` at `1bf5766`:

- `tenants.slug` exists and is unique (`app/modules/organization/infrastructure/models.py`), so it can identify a tenant in a public URL.
- `requisitions` has no open/published state, so nothing says which jobs may be listed publicly.
- `candidate_cases` has `UniqueConstraint("tenant_id", "email")`: a tenant can hold only one case per email. `created_by` is a non-null FK to `users`, and so is `candidate_attachments.created_by`.
- Uploads go through `AttachmentService.upload` (`app/modules/attachments/application/attachment_service.py`). It already checks the filename, size (`Settings.attachment_max_bytes`, 5 MiB), the content-type allow-list (PDF, DOCX) and the file signature (`%PDF-` / `PK\x03\x04`), then runs a synchronous ClamAV scan over the network (`clamd` in `docker-compose.yml`, ADR-003). An infected file raises `MalwareScanRejectedError`. When the scanner is unavailable, `MalwareScannerUnavailableError` fails the upload closed with `503`.
- Rate limiting is one global fixed-window limiter per client IP (`app/shared/rate_limit.py`, 120 req/min, Redis), which trusts `X-Forwarded-For` only from `RATE_LIMIT_TRUSTED_PROXY_CIDRS`.
- The web app (`web/`, ADR-004) puts every page under the `(app)` route group, whose layout requires a session. Browser API calls go through the session-attaching BFF at `/api/tf/[...path]`.

## Decisions from the requester (duthaho, on this issue, 2026-11-26)

1. A repeat application from an email that already has a case in the tenant uses the existing case. No second case is created.
2. Consent text is one platform-wide text, versioned in code. The rendered text, its version and the timestamp are stored on the case and shown on the candidate detail page.
3. Requisitions get a `published` flag that can be set both through the API and from the web app.
4. Applicants get no confirmation email. The page shows an on-screen confirmation only.

## Goals

- Each tenant has a public careers page that lists its published requisitions. An anonymous visitor can apply to one of them with name, email, a CV and explicit consent.
- A valid application creates a candidate case in `applied` whose CV has already passed signature checks and the malware scan.
- Abuse controls are enforced and tested: per-route rate limits, a honeypot field, a request-size cap, and type, size and signature checks on the file.
- Consent text, version and timestamp are stored with the case and shown to staff on the candidate detail page.
- Staff can publish and unpublish requisitions through the API and from the web app.
- The responses reveal nothing about who has already applied (no email enumeration).

## Non-goals

- CAPTCHA or any third-party bot check. The honeypot and the rate limits are the controls for this issue.
- Any email to applicants, including confirmations and status updates.
- Applicants viewing, editing or withdrawing an application, and any applicant accounts or login.
- Several candidate cases per person in one tenant. The existing unique constraint stays.
- Per-tenant editable consent text, or consent withdrawal flows (DSAR is DUTH-69).
- Job description content beyond today's `title` and `department` fields.
- Domain events for applications on RabbitMQ. DUTH-58/59 define and publish events; this issue writes audit events only.
- Custom domains or a careers host per tenant. The URL is path-based: `/careers/<tenant-slug>`.

## Users and use cases

| Actor | Auth | Use case |
|---|---|---|
| Applicant | Anonymous | Open `/careers/<slug>`, pick a published job, fill in the form, upload a CV, accept consent, submit, see "application received". |
| Bot / attacker | Anonymous | Floods the form, fills hidden fields, uploads oversized, disguised or infected files, probes whether an email has applied. Every attempt is rejected or absorbed without effect and without revealing state. |
| Recruiter / tenant admin | `requisition:create` | Publish or unpublish a requisition from Settings → Requisitions or through the API. See the new case on the pipeline board, its source, and its consent record on the candidate detail page. |
| Hiring manager / auditor | `tenant:read` | See the source and consent record on the candidate detail page (read-only). |

## Contract

Public routes live under `/v1/public/...`. They have no auth dependency and never read a bearer token. Errors use the existing problem+json types (`docs/api-errors.md`). A new type is added only where noted.

### 1. `GET /v1/public/tenants/{slug}/requisitions`

```json
{
  "tenant": { "name": "Acme", "slug": "acme" },
  "upload_policy": { "max_bytes": 5242880, "content_types": ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"] },
  "requisitions": [
    { "id": "…", "title": "Backend Engineer", "department": "Engineering", "published_at": "2026-11-20T09:00:00Z" }
  ]
}
```

- Only `published = true` requisitions, newest `published_at` first, capped at 100 (no pagination in this issue).
- `404` (`not-found`) for an unknown slug. The response never contains ids of users, memberships or unpublished requisitions.

### 2. `GET /v1/public/tenants/{slug}/consent`

```json
{ "version": "careers-v1", "text": "By applying you agree that Acme processes … for 365 days …" }
```

- The text is a template versioned in code. It is rendered with the tenant name and, when the tenant has a retention policy, its `retention_days`. Without a policy it uses the wording "for as long as needed for recruiting, then deleted under Acme's retention policy".
- The page shows exactly this text, and the server stores exactly this rendered text on the case.

### 3. `POST /v1/public/tenants/{slug}/requisitions/{requisition_id}/applications`

`multipart/form-data` fields: `first_name` (1–100), `last_name` (1–100), `email` (valid, ≤ 320, trimmed and lower-cased), `consent_version` (must equal the current version), `consent_accepted` (must be `true`), `cv` (file), and `website` (honeypot; must be empty).

Processing order (later steps run only when the earlier ones pass):

1. **Request cap.** If `Content-Length` is missing or larger than `attachment_max_bytes + 64 KiB`, return `413` (`payload-too-large`, new type) before the body is parsed.
2. **Rate limit.** At most `CAREERS_APPLY_LIMIT_PER_HOUR` (default 5) per client IP per hour, keyed separately from the global limiter, and at most `CAREERS_APPLY_LIMIT_PER_EMAIL_PER_DAY` (default 3) per tenant + normalized email per day. Return `429` (`rate-limited`) with `Retry-After`. The email-keyed limit returns the same `429` body as the IP limit.
3. **Honeypot.** If `website` is non-empty, return the normal `202` response, store nothing, scan nothing, and increment `careers_applications_total{outcome="honeypot"}`.
4. **Tenant and requisition.** An unknown slug, an unknown requisition, another tenant's requisition or an unpublished requisition all return the same `404` (`not-found`).
5. **Fields and consent.** A validation failure, a missing consent or a stale `consent_version` return `422` (`validation-error`). A stale version tells the page to reload the text.
6. **File.** The existing `_validate` rules apply: name, size, allow-list and signature (`422`). Then the ClamAV scan runs: an infected file returns `422` (`validation-error`, "file was rejected"), and an unavailable scanner returns `503` (fail closed). Both stores nothing.
7. **Existing case.** If the tenant already has a case whose email matches (case-insensitive), no case or attachment is created. The response is the normal `202`, and one audit event `candidate.reapplied` is written on the existing case with the requisition id. The CV is discarded, so nobody can attach files to another person's case by knowing their email.
8. **Create.** In one transaction: the candidate case (`stage = applied`, `source = careers`, `created_by = system:careers`), the CV attachment (`document_type = resume`), the consent record, and the audit events `candidate.created` and `attachment.uploaded` with `actor_id = system:careers`. A unique-constraint race on `(tenant_id, email)` is handled as step 7.

Response for steps 3, 7 and 8:

```json
{ "status": "received" }
```

with `202 Accepted`. The body and status are identical for all three, so a caller cannot tell a new applicant from a known one or a honeypot hit.

### 4. `PATCH /v1/requisitions/{id}/publication` — `requisition:create`

Request `{ "published": true }`. Response: the requisition with `published` and `published_at`. Setting the current value again is a no-op that returns `200`. Publishing sets `published_at = now`; unpublishing clears it. Each change writes the audit event `requisition.published` or `requisition.unpublished`. Another tenant's id returns `404`.

### 5. Changes to existing staff responses

- `GET /v1/requisitions` items gain `published` (bool) and `published_at` (nullable).
- `GET /v1/candidate-cases/{id}` gains `source` (`"staff"` or `"careers"`) and `consent` (`{ "version", "text", "accepted_at" }` or `null`). These are additive fields; no existing field changes.

OpenAPI is regenerated into `web/openapi.json` and `web/src/lib/api/schema.ts` in the same PR.

## Data model (expand-only Alembic migration)

- `requisitions`: add `published boolean not null default false` and `published_at timestamptz null`.
- `candidate_cases`: add `source varchar(20) not null default 'staff'`.
- New table `candidate_consents`: `candidate_case_id` (PK, FK → `candidate_cases` on delete cascade), `tenant_id`, `version`, `text`, `accepted_at`. The text is stored as rendered, so a later template change does not rewrite history.
- Insert the system user `users(id = 'system:careers', email = null)`, so `created_by` FKs stay non-null and audit stays attributable. The id cannot clash with Keycloak subjects, which are UUIDs.
- Retention: a careers case is a normal candidate case, so the retention job anonymizes it the same way. It also clears `candidate_consents.text`, keeping only the version and timestamp as proof that consent was given.

## Web

- A new route group `web/src/app/(public)/careers/[tenantSlug]/` outside `(app)`, so no session is required. It has a list page and an apply page per requisition. The pages render server-side from the public API.
- The apply form posts to a Next route handler (`/api/public/careers/...`). The handler forwards the multipart body to the API with the visitor's IP in `X-Forwarded-For`. Compose sets `RATE_LIMIT_TRUSTED_PROXY_CIDRS` to the web container's network so the API rate-limits the real client. The handler never attaches the BFF session cookie or token.
- The honeypot field is visually hidden (not `display:none` only), has `tabindex="-1"` and `autocomplete="off"`, and its label tells screen-reader users to leave it empty.
- The form pre-checks size and type using `upload_policy` from the public listing (`GET /v1/attachment-policy` needs a session, so it cannot be used here). The server remains authoritative.
- After a `202` the page shows "Application received". `413`, `422`, `429` and `503` show specific, non-technical messages.
- Settings gains a Requisitions page listing requisitions with a published switch, shown to roles that have `requisition:create`. It also shows the public careers URL for the tenant.
- The candidate detail page shows "Source: careers page" and a Consent panel with the version, the accepted time and the stored text.

## Acceptance criteria

- AC1: Given a tenant with a published requisition, when an anonymous user submits the form with valid fields, consent and a clean PDF CV, then the API returns `202`, a case exists in `applied` with `source = careers`, its attachment is stored and was scanned, and audit events `candidate.created` and `attachment.uploaded` with actor `system:careers` exist. *(Issue AC1)*
- AC2: Given an unpublished requisition, a requisition of another tenant or an unknown slug, when anyone lists or applies, then the requisition is not listed and applying returns `404`.
- AC3: Given a file that fails the size, type or signature checks, or that ClamAV flags (EICAR test file), when it is submitted, then the API returns `413` or `422` and no case, attachment or object is stored. When the scanner is down it returns `503` and stores nothing. *(Issue AC2)*
- AC4: Given a non-empty honeypot field, when the form is submitted, then the response equals the success response and nothing is stored. *(Issue AC2)*
- AC5: Given more than the per-IP or per-email limit within the window, when another application arrives, then it returns `429` with `Retry-After`, and the IP limit uses `X-Forwarded-For` only from trusted proxies. *(Issue AC2)*
- AC6: Given an email that already has a case in the tenant (in any letter case), when it applies again, then the response equals the success response, no case or attachment is created, and `candidate.reapplied` is audited on the existing case.
- AC7: Given a careers case, when staff open its detail page, then the source and the consent version, accepted time and exact text shown at apply time are displayed. Staff-created cases show no consent panel. *(Issue AC3)*
- AC8: Given a user with `requisition:create`, when they toggle published in Settings → Requisitions or call the publication API, then the careers page reflects it and an audit event is written. Roles without the permission get `403` and see no switch.
- AC9: Given a careers case past the tenant's retention period, when the retention job runs, then the case is anonymized and its consent text is cleared, while the version and timestamp remain.
- AC10: `ruff format --check`, `ruff check`, `python -m pytest` (coverage ≥ 85%), the architecture tests, web lint, typecheck, unit tests and build all pass. A Playwright test covers publish → apply → see the case and its consent.

## Constraints

- Domain and application layers stay framework-free (`tests/architecture`). The public apply use case lives in the candidates module and reuses `AttachmentService` validation and scanning rather than copying them.
- Schema changes are additive only (expand). No existing column changes type or nullability.
- No real PII in fixtures or seed. The seed publishes two demo requisitions and prints the careers URL.
- New settings are listed by name in the README: `CAREERS_APPLY_LIMIT_PER_HOUR` and `CAREERS_APPLY_LIMIT_PER_EMAIL_PER_DAY`, plus `RATE_LIMIT_TRUSTED_PROXY_CIDRS` set for the web container in compose.
- A short ADR or doc section explains the untrusted-input pipeline (cap → limit → honeypot → validate → scan → dedupe) and the anti-enumeration response. This repo is a teaching artifact.

## Risks

- **Distributed abuse beats per-IP limits.** A botnet or IPv6 rotation can stay under 5/hour/IP. Mitigations: the per-email limit, a scanner-bound cost per request, and the metric `careers_applications_total{outcome}` to watch. CAPTCHA stays a documented follow-up.
- **ClamAV cost per request.** Each application streams up to 5 MiB to `clamd`. The request cap and the IP limit run before the scan to bound this. A scanner outage blocks applications (`503`) by design.
- **Wrong trusted-proxy config.** If `RATE_LIMIT_TRUSTED_PROXY_CIDRS` is too wide, clients can spoof `X-Forwarded-For`. If it is too narrow, all applicants share the web container's IP and hit the limit together. Tests cover both, and the compose value is documented.
- **Timing side channel on existing emails.** Step 7 skips the storage write, so a known email can answer slightly faster. This is accepted for a showcase and noted in the ADR. The scan runs for both paths, which keeps most of the difference small.
- **DOCX is a ZIP.** The signature check proves only that the file is a ZIP. ClamAV scans archive contents. Files are never rendered or parsed server-side in this issue (resume parsing is DUTH-72).
- **Seeing the consent text is PII-adjacent.** The text contains no applicant data, only tenant wording, so showing it to `tenant:read` roles is safe.

## Open questions

None. The four product questions were answered on the issue on 2026-11-26 (see Decisions).

## Rollout and rollback

- Migration is expand-only with safe defaults: existing requisitions start unpublished, so no careers page lists anything until staff publish a job.
- Rollback: revert the app. The new columns and table are ignored by older code. The migration downgrade drops the new columns and table but keeps the `system:careers` user, because careers cases and attachments still reference it.
- No feature flag in this issue (feature flags arrive in DUTH-65). Unpublishing every requisition turns the public page off functionally.

## Plan

(added at the `plan` step)
