# Requisition publication

Staff can manage publication at Settings → Requisitions. Users with
`requisition:create` (tenant admins and recruiters) see the publication switch;
other users with `tenant:read` see a read-only list. The page displays the tenant's
`/careers/<slug>` URL. The public page and application flow ship in DUTH-127.

`PATCH /v1/requisitions/{id}/publication` accepts `{ "published": true }` or
`{ "published": false }` and returns the requisition, including `published` and
nullable `published_at`. Publishing records the current UTC time; unpublishing
clears it. Repeating the current value returns `200`, preserves the timestamp,
and writes no audit event. A change writes `requisition.published` or
`requisition.unpublished` in the same transaction. PostgreSQL row locking
serializes changes to the same requisition.

The endpoint requires `requisition:create`; missing permission returns `403`.
An unknown or other tenant's requisition returns `404`. The body must contain a
JSON boolean; invalid input returns `422`. Errors use existing problem+json
responses. `GET /v1/requisitions` items include the publication fields and the
envelope includes `tenant_slug`, allowing the page to construct the careers URL
even when the tenant has no requisitions. OpenAPI and the generated web client
document these additive fields.

The organization application use case stays framework-free and uses the existing
repository and unit-of-work ports. No dependency or new runtime setting is needed.

Migration `d126a001` adds the columns and the partial public-listing index.
Existing rows default to unpublished. Upgrade before deploying the app; older
app versions ignore these additive columns. To roll back, restore the older app
first and then downgrade the migration. Downgrade preserves requisitions but
discards publication state. Candidate, consent and system-user migrations belong
to DUTH-127.

The local demo seed creates two published requisitions and prints
`/careers/talentflow-demo`. Re-running it preserves their publication timestamps.

The PostgreSQL migration/concurrency test is opt-in through
`PUBLICATION_TEST_DATABASE_URL`. Point it only at an empty, disposable local
database; it runs upgrade/downgrade and inserts test rows. Run it with
`uv run python -m pytest tests/integration/test_publication_postgres.py --no-cov`.
