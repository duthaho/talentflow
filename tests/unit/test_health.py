from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.settings import Settings


def test_health_reports_service_status() -> None:
    with TestClient(create_app("sqlite://")) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_only_configured_origin() -> None:
    app = create_app(
        "sqlite://",
        app_settings=Settings(cors_allowed_origins="https://console.example.test"),
    )
    with TestClient(app) as client:
        allowed = client.options(
            "/health",
            headers={
                "Origin": "https://console.example.test",
                "Access-Control-Request-Method": "GET",
            },
        )
        denied = client.options(
            "/health",
            headers={
                "Origin": "https://untrusted.example.test",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://console.example.test"
    assert denied.status_code == 400


def test_liveness_readiness_and_metrics_expose_operational_signals() -> None:
    with TestClient(create_app("sqlite://")) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")
        metrics = client.get("/metrics")

    assert live.json() == {"status": "ok"}
    assert ready.json() == {"status": "ok"}
    assert metrics.status_code == 200
    assert "talentflow_http_requests_total" in metrics.text
