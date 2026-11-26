"""Translate HTTP validators at the edge; commands compare versions."""

import re
from typing import Annotated

from fastapi import Header, HTTPException

from app.shared.concurrency import (
    InvalidVersionPreconditionError,
    VersionPreconditionFailedError,
    VersionPreconditionRequiredError,
)

IfMatch = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description=(
            'Strong aggregate ETag, e.g. "3", a list of strong tags, or *. '
            "Alternative to expected_version; both must agree. Missing: 428; stale: 412; "
            "malformed or conflicting: 400. Idempotent replays are resolved first."
        ),
    ),
]

ETAG_HEADER = {
    "description": 'Strong aggregate version validator, e.g. "3". See ADR-006.',
    "schema": {"type": "string"},
}
ETAG_RESPONSE = {200: {"headers": {"ETag": ETAG_HEADER}}}
_PROBLEM_CONTENT = {
    "application/problem+json": {
        "schema": {
            "type": "object",
            "required": ["type", "title", "status", "detail", "instance", "correlation_id"],
            "properties": {
                "type": {"type": "string", "format": "uri"},
                "title": {"type": "string"},
                "status": {"type": "integer"},
                "detail": {"type": "string"},
                "instance": {"type": "string"},
                "correlation_id": {"type": "string"},
                "current_version": {"type": "integer"},
            },
            "additionalProperties": True,
        }
    }
}
CONDITIONAL_RESPONSES = {
    **ETAG_RESPONSE,
    400: {"description": "Invalid or contradictory preconditions", "content": _PROBLEM_CONTENT},
    412: {
        "description": "Precondition failed; refetch before retrying",
        "content": _PROBLEM_CONTENT,
        "headers": {"ETag": ETAG_HEADER},
    },
    428: {
        "description": "Supply If-Match or expected_version",
        "content": _PROBLEM_CONTENT,
    },
}


def etag(version: int) -> str:
    return f'"{version}"'


def precondition_exception(
    error: InvalidVersionPreconditionError
    | VersionPreconditionFailedError
    | VersionPreconditionRequiredError,
) -> HTTPException:
    if isinstance(error, VersionPreconditionFailedError):
        return HTTPException(
            412,
            detail={
                "detail": str(error),
                "problem_type": "precondition-failed",
                "current_version": error.current_version,
            },
            headers={"ETag": etag(error.current_version)},
        )
    required = isinstance(error, VersionPreconditionRequiredError)
    return HTTPException(
        428 if required else 400,
        detail={
            "detail": str(error),
            "problem_type": "precondition-required" if required else "invalid-precondition",
        },
        headers={"Cache-Control": "no-store"},
    )


def parse_if_match(values: list[str] | None) -> tuple[str, ...] | None:
    if values is None:
        return None
    value = ",".join(values).strip(" \t")
    if value == "*":
        return ("*",)
    # etagc allows commas inside a quoted opaque tag, but no quotes, spaces or controls.
    tag = r'"[\x21\x23-\x7e\x80-\xff]*"'
    if not re.fullmatch(rf"{tag}(?:[ \t]*,[ \t]*{tag})*", value):
        raise precondition_exception(
            InvalidVersionPreconditionError("If-Match must contain strong quoted tags or *")
        )
    return tuple(token[1:-1] for token in re.findall(tag, value))
