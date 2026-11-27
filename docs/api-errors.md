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

## internal-error

An unexpected server failure occurred. Its detail never exposes exception data.

## service-unavailable

A required dependency is temporarily unavailable.

## length-required

`411` on public careers application uploads without an explicit `Content-Length`,
with invalid length, or with any `Transfer-Encoding`. This check runs before
multipart parsing. The same-origin web handler supplies the actual buffered length.

## payload-too-large

`413` when a public application body exceeds `ATTACHMENT_MAX_BYTES + 65536`,
including when the streamed bytes exceed a misleading declared length. Choose a
smaller CV. File validation within the body cap still uses `422`.

Public careers requests also return `503` (`service-unavailable`) when Redis,
ClamAV, or the API upstream is unavailable. No application is persisted when
quota or malware scanning cannot complete. Retry later; a `429` includes
`Retry-After`. A stale consent version returns `422`: reload and accept the text.
