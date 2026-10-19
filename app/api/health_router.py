from fastapi import APIRouter, Request, status
from sqlalchemy import text
from starlette.responses import JSONResponse

from app.shared.observability import prometheus_response

router = APIRouter(tags=["operations"])


@router.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(request: Request):
    try:
        with request.app.state.session_factory() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"status": "unavailable"}
        )
    return {"status": "ok"}


@router.get("/metrics", include_in_schema=False)
def metrics():
    return prometheus_response()
