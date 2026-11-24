from fastapi import APIRouter, Request, status
from sqlalchemy import text

from app.shared.observability import prometheus_response
from app.shared.problem_details import problem_response, problem_type

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
        return problem_response(
            request,
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service is unavailable",
            type_uri=problem_type("service-unavailable"),
        )
    return {"status": "ok"}


@router.get("/metrics", include_in_schema=False, tags=["operations"])
def metrics():
    return prometheus_response()
