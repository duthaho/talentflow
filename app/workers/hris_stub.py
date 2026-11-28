"""Demonstration HRIS. Volatile data; bearer authentication on all employee routes."""

import os
import secrets
from datetime import UTC, date, datetime
from threading import Lock
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field


class Employee(BaseModel):
    tenant_id: UUID
    candidate_case_id: UUID
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=320)
    start_date: date


def create_app(token=None):
    expected = token or os.environ.get("HRIS_STUB_TOKEN", "")
    if not expected:
        raise ValueError("HRIS_STUB_TOKEN is required")
    records = {}
    lock = Lock()
    app = FastAPI(title="Development HRIS stub")

    def authenticated(authorization: str | None = Header(default=None)):
        if not secrets.compare_digest(authorization or "", "Bearer " + expected):
            raise HTTPException(401, "Unauthorized")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.put("/v1/employees/{key}", dependencies=[Depends(authenticated)])
    def put(key: UUID, body: Employee, response: Response):
        key = str(key)
        with lock:
            old = records.get(key)
            record = {
                **body.model_dump(mode="json"),
                "key": key,
                "employee_id": old["employee_id"] if old else str(uuid4()),
                "created_at": old["created_at"] if old else datetime.now(UTC).isoformat(),
            }
            records[key] = record
            response.status_code = 200 if old else 201
            return record

    @app.get("/v1/employees/{key}", dependencies=[Depends(authenticated)])
    def get(key: UUID):
        with lock:
            if str(key) not in records:
                raise HTTPException(404, "Not found")
            return records[str(key)]

    @app.delete("/v1/employees/{key}", dependencies=[Depends(authenticated)], status_code=204)
    def delete(key: UUID):
        with lock:
            if records.pop(str(key), None) is None:
                raise HTTPException(404, "Not found")

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=8090, access_log=False)
