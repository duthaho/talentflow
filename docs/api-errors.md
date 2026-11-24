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
