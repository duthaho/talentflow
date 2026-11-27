from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.shared.observability import correlation_id_context

PROBLEM_TYPE_BASE = "https://github.com/duthaho/talentflow/blob/main/docs/api-errors.md#"
PROBLEM_TYPES = frozenset(
    {
        "validation-error",
        "length-required",
        "payload-too-large",
        "invalid-precondition",
        "precondition-failed",
        "precondition-required",
        "unauthorized",
        "version-conflict",
        "rate-limited",
        "not-found",
        "forbidden",
        "conflict",
        "internal-error",
        "service-unavailable",
    }
)

_STATUS_TITLES = {
    411: "Length Required",
    413: "Payload Too Large",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    410: "Gone",
    412: "Precondition Failed",
    428: "Precondition Required",
    422: "Unprocessable Content",
    429: "Too Many Requests",
    500: "Internal Server Error",
    503: "Service Unavailable",
}
_STATUS_TYPES = {
    411: "length-required",
    413: "payload-too-large",
    401: "unauthorized",
    403: "forbidden",
    404: "not-found",
    409: "conflict",
    422: "validation-error",
    429: "rate-limited",
    500: "internal-error",
    503: "service-unavailable",
}


def problem_type(slug: str) -> str:
    if slug not in PROBLEM_TYPES:
        raise ValueError(f"Unknown problem type: {slug}")
    return f"{PROBLEM_TYPE_BASE}{slug}"


def install_problem_details_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exception: HTTPException | StarletteHTTPException
    ) -> JSONResponse:
        detail, extensions = _detail_and_extensions(exception.detail)
        slug = extensions.pop("problem_type", _STATUS_TYPES.get(exception.status_code))
        return problem_response(
            request,
            status=exception.status_code,
            detail=detail,
            type_uri=problem_type(slug) if slug else "about:blank",
            extensions=extensions,
            headers=exception.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exception: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {"pointer": _json_pointer(error["loc"]), "detail": error["msg"]}
            for error in exception.errors()
        ]
        return problem_response(
            request,
            status=422,
            detail="Request validation failed",
            type_uri=problem_type("validation-error"),
            extensions={"errors": errors},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, _: Exception) -> JSONResponse:
        return problem_response(
            request,
            status=500,
            detail="An unexpected error occurred",
            type_uri=problem_type("internal-error"),
        )


def problem_response(
    request: Request,
    *,
    status: int,
    detail: str,
    type_uri: str,
    extensions: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    correlation_id = (
        correlation_id_context.get()
        or getattr(request.state, "correlation_id", None)
        or str(uuid4())
    )
    request.state.correlation_id = correlation_id
    response_headers = dict(headers or {})
    response_headers["X-Correlation-Id"] = correlation_id
    body: dict[str, Any] = {
        "type": type_uri,
        "title": _STATUS_TITLES.get(status, "HTTP Error"),
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "correlation_id": correlation_id,
    }
    if extensions:
        body.update(extensions)
    return JSONResponse(
        status_code=status,
        content=body,
        headers=response_headers,
        media_type="application/problem+json",
    )


def _detail_and_extensions(detail: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(detail, Mapping):
        values = dict(detail)
        return str(values.pop("detail", "Request failed")), values
    return str(detail), {}


def _json_pointer(location: tuple[Any, ...]) -> str:
    components = location[1:] if location and location[0] in {"body", "query", "path"} else location
    return "/" + "/".join(
        str(component).replace("~", "~0").replace("/", "~1") for component in components
    )
