"""Route seam: authorization precedes reservation and every replay."""

import hashlib
import inspect
import json
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, Request, Response
from fastapi.routing import APIRoute
from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.modules.identity.security import ActorContext, resolve_actor
from app.shared.database import SessionDep
from app.shared.idempotency import IdempotencyRecord


class Replay(Exception):
    def __init__(self, record: IdempotencyRecord):
        self.response = Response(
            content=json.dumps(record.body, ensure_ascii=False, separators=(",", ":")),
            status_code=record.status_code,
            headers={**record.headers, "Idempotent-Replayed": "true"},
        )


def _busy() -> HTTPException:
    return HTTPException(
        409, "Command is still in progress; retry later", headers={"Retry-After": "1"}
    )


def fingerprint(request: Request, body: object) -> str:
    value = [request.method, request.scope["route"].path_format, request.path_params, body]
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _reserve(request: Request, session: Session, actor: ActorContext, key: str, digest: str):
    now = datetime.now(UTC)
    scope = (
        IdempotencyRecord.tenant_id == actor.tenant_id,
        IdempotencyRecord.actor_id == actor.actor_id,
        IdempotencyRecord.key == key,
    )
    dialect = session.get_bind().dialect.name
    try:
        if dialect == "postgresql":
            # Transaction-local: never leak the timeout to another pooled request.
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
        session.execute(
            delete(IdempotencyRecord).where(*scope, IdempotencyRecord.expires_at <= now)
        )
        record_id = str(uuid4())
        insert = pg_insert if dialect == "postgresql" else sqlite_insert
        inserted = session.scalar(
            insert(IdempotencyRecord)
            .values(
                id=record_id,
                tenant_id=actor.tenant_id,
                actor_id=actor.actor_id,
                key=key,
                fingerprint=digest,
                state="in_progress",
                expires_at=now
                + timedelta(seconds=request.app.state.runtime_settings.idempotency_key_ttl_seconds),
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "actor_id", "key"])
            .returning(IdempotencyRecord.id)
        )
    except OperationalError as error:
        session.rollback()
        if getattr(error.orig, "sqlstate", None) == "55P03" or "database is locked" in str(
            error.orig
        ):
            raise _busy() from error
        raise
    if inserted:
        request.state.idempotency_reservation = (session, record_id)
        return
    record = session.scalar(select(IdempotencyRecord).where(*scope))
    if record is None:
        raise _busy()  # A concurrent expiry cleanup removed it; retry safely.
    if record.fingerprint != digest:
        raise HTTPException(422, "Idempotency-Key was already used for a different command")
    if record.state == "completed":
        raise Replay(record)
    raise _busy()


async def guard(
    request: Request,
    session: SessionDep,
    actor: Annotated[ActorContext, Depends(resolve_actor)],
    key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description=(
                "Optional retry key: 1–255 visible ASCII characters. Scoped to tenant and actor; "
                "same command replays its successful response; different command returns 422; "
                "in-progress command returns 409 with Retry-After."
            ),
        ),
    ] = None,
) -> None:
    if key is None:
        return
    if not 1 <= len(key) <= 255 or any(not 0x21 <= ord(char) <= 0x7E for char in key):
        raise HTTPException(400, "Idempotency-Key must contain 1–255 visible ASCII characters")
    try:
        body = await request.json() if await request.body() else None
    except (ValueError, UnicodeDecodeError) as error:
        raise HTTPException(422, "Request body must be valid JSON") from error
    await run_in_threadpool(_reserve, request, session, actor, key, fingerprint(request, body))


def _complete(session: Session, record_id: str, response: Response) -> None:
    session.execute(
        update(IdempotencyRecord)
        .where(
            IdempotencyRecord.id == record_id,
            IdempotencyRecord.state == "in_progress",
        )
        .values(
            state="completed",
            status_code=response.status_code,
            body=json.loads(response.body) if response.body else None,
            headers={
                name: value
                for name, value in response.headers.items()
                if name.lower() in {"content-type", "location"}
            },
        )
    )
    session.commit()


class CommandRoute(APIRoute):
    """Append the guard after route dependencies, including current permissions."""

    def __init__(self, path, endpoint, **kwargs):
        if (
            "POST" in (kwargs.get("methods") or [])
            and path != "/v1/tenants"
            and not getattr(endpoint, "__idempotent_command__", False)
        ):
            original_endpoint = endpoint

            @wraps(original_endpoint)
            def command(*args, **values):
                values.pop("_idempotency", None)
                return original_endpoint(*args, **values)

            @wraps(original_endpoint)
            async def async_command(*args, **values):
                values.pop("_idempotency", None)
                return await original_endpoint(*args, **values)

            endpoint = async_command if inspect.iscoroutinefunction(original_endpoint) else command
            signature = inspect.signature(original_endpoint)
            endpoint.__signature__ = signature.replace(
                parameters=[
                    *signature.parameters.values(),
                    inspect.Parameter(
                        "_idempotency",
                        inspect.Parameter.KEYWORD_ONLY,
                        default=Depends(guard),
                        annotation=None,
                    ),
                ]
            )
            endpoint.__idempotent_command__ = True
        super().__init__(path, endpoint, **kwargs)

    def get_route_handler(self):
        if "POST" not in self.methods or self.path == "/v1/tenants":
            return super().get_route_handler()
        original = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                response = await original(request)
                reservation = getattr(request.state, "idempotency_reservation", None)
                if reservation and 200 <= response.status_code < 300:
                    await run_in_threadpool(_complete, *reservation, response)
                elif reservation:
                    await run_in_threadpool(reservation[0].rollback)
                return response
            except Replay as replay:
                return replay.response
            except Exception:
                reservation = getattr(request.state, "idempotency_reservation", None)
                if reservation:
                    # Uncommitted reservations disappear. A committed reservation stays
                    # in_progress if response finalization fails: never execute twice.
                    await run_in_threadpool(reservation[0].rollback)
                raise

        return handle
