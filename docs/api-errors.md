# API error types

TalentFlow returns errors as `application/problem+json` following RFC 9457. The
`type` field is an opaque, stable identifier; clients must compare it as a full
string and must not parse it. This document's GitHub URL and the heading anchor
form the canonical base for those identifiers. Moving this document or renaming
the repository is a breaking API contract change that requires an ADR.

Every problem includes `type`, `title`, `status`, `detail`, `instance`, and
`correlation_id`. Validation problems also include `errors`, a list of objects
with JSON Pointer `pointer` and human-readable `detail` fields.

## validation-error

The request did not satisfy the endpoint's input contract.

## unauthorized

The caller must authenticate or present valid credentials before retrying.

## version-conflict

An optimistic-lock version was stale. The response includes `current_version`.

## invalid-precondition

400: `If-Match` is malformed (including weak or unquoted tags), or the header
and body `expected_version` disagree. Supply strong quoted tags or a lone `*`.

## precondition-failed

412: `If-Match` did not match the aggregate version, or a conditional write lost
a concurrent update race. The response includes the current `ETag` header and
`current_version`. Refetch before choosing whether to retry the command.

## precondition-required

428: a candidate stage transition or offer approval supplied neither `If-Match`
nor `expected_version`. This response is not cacheable. Read the aggregate first
and send its ETag with the command.

## rate-limited

The request exceeded the configured rate limit. The response retains `Retry-After`.

## not-found

The requested resource does not exist or is not visible to the caller.

## forbidden

The caller is authenticated but is not authorized for the requested operation.

## conflict

The request conflicts with the current resource state.

## webhook-url-not-allowed

422: a webhook endpoint URL breaks the outbound policy in ADR-008 §4: the scheme,
port, userinfo, fragment or length, a blocked host name, or a resolved address
that is not public. `errors[0].pointer` is `/url`. The detail names the rule and
never echoes the resolved address. Registered by DUTH-62.

## webhook-endpoint-limit-reached

409: the tenant already has 10 webhook endpoints that are not deleted. Delete
one before registering another. Registered by DUTH-62.

## delivery-not-redeliverable

409: a redelivery was requested while the original delivery is still pending,
the endpoint is not enabled, or the same event already has a pending delivery to
that endpoint. Wait for the delivery to finish, or re-enable the endpoint.
Registered by DUTH-62.

## internal-error

An unexpected server failure occurred. Its detail never exposes exception data.

## service-unavailable

A required dependency is temporarily unavailable.
