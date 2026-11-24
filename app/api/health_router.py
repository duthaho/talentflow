from fastapi import APIRouter, Request, status
from sqlalchemy import text
from starlette.responses import JSONResponse

from app.shared.observability import prometheus_response

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/live", tags=["operations"])
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", tags=["operations"])
def readiness(request: Request):
    try:
        with request.app.state.session_factory() as session:
            session.execute(text("SELECT 1"))
        request.app.state.rate_limiter.ping()
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"status": "unavailable"}
        )
    return {"status": "ok"}


@router.get("/metrics", include_in_schema=False, tags=["operations"])
def metrics():
    return prometheus_response()
