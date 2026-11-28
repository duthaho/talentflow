from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import sessionmaker

import app.shared.models  # noqa: F401 - register every bounded-context mapping
from app.api.attachment_router import policy_router as attachment_policy_router
from app.api.attachment_router import router as attachment_router
from app.api.audit_router import router as audit_router
from app.api.calendar_router import router as calendar_router
from app.api.candidate_router import router as candidate_router
from app.api.health_router import router as health_router
from app.api.identity_router import router as identity_router
from app.api.interview_router import router as interview_router
from app.api.offer_router import router as offer_router
from app.api.organization_router import router as organization_router
from app.api.public_careers_router import router as public_careers_router
from app.api.reporting_router import router as reporting_router
from app.api.retention_router import router as retention_router
from app.api.webhook_contract import install_webhook_openapi
from app.api.webhook_router import commands as webhook_commands
from app.api.webhook_router import router as webhook_router
from app.modules.feature_flags.infrastructure.openfeature import OpenFeatureFlags
from app.modules.identity.infrastructure.jwt_validator import HttpJwksProvider, JwtValidator
from app.shared.database import Base, build_engine
from app.shared.observability import configure_logging, configure_telemetry, instrument_app
from app.shared.problem_details import install_problem_details_handlers
from app.shared.rate_limit import (
    MemoryFixedWindowRateLimiter,
    RedisFixedWindowRateLimiter,
    install_rate_limit_middleware,
)
from app.shared.settings import Settings, settings
from app.shared.system_users import ensure_system_users


def create_app(database_url: str | None = None, app_settings: Settings | None = None) -> FastAPI:
    runtime_settings = app_settings or settings
    configure_telemetry(runtime_settings)
    configure_logging()
    engine = build_engine(database_url or runtime_settings.database_url)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    rate_limiter = (
        RedisFixedWindowRateLimiter(runtime_settings.redis_url)
        if runtime_settings.redis_url
        else MemoryFixedWindowRateLimiter()
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if runtime_settings.app_env != "production":
            Base.metadata.create_all(engine)
            with session_factory() as session:
                ensure_system_users(session)
        app.state.feature_flags = OpenFeatureFlags(runtime_settings)
        try:
            yield
        finally:
            app.state.feature_flags.close()
            rate_limiter.close()
            engine.dispose()

    app = FastAPI(title="TalentFlow API", version="0.1.0", lifespan=lifespan)
    if runtime_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(runtime_settings.cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "X-Correlation-Id",
                "Idempotency-Key",
                "If-Match",
            ],
            expose_headers=["Idempotent-Replayed", "Retry-After", "ETag"],
        )
    app.state.session_factory = session_factory
    app.state.rate_limiter = rate_limiter
    app.state.auth_mode = runtime_settings.auth_mode
    app.state.runtime_settings = runtime_settings
    install_problem_details_handlers(app)
    install_rate_limit_middleware(
        app,
        limiter=rate_limiter,
        enabled=runtime_settings.rate_limit_enabled,
        requests_per_minute=runtime_settings.rate_limit_requests_per_minute,
        trusted_proxy_cidrs=runtime_settings.trusted_proxy_cidrs(),
    )
    if runtime_settings.auth_mode == "oidc_jwt":
        app.state.token_validator = JwtValidator(
            issuer=runtime_settings.oidc_issuer,
            audience=runtime_settings.oidc_audience,
            algorithms=("RS256",),
            jwks=HttpJwksProvider(
                url=runtime_settings.oidc_jwks_url,
                cache_ttl_seconds=runtime_settings.oidc_jwks_cache_ttl_seconds,
            ),
        )
    instrument_app(app)
    for router in (
        public_careers_router,
        attachment_router,
        attachment_policy_router,
        audit_router,
        calendar_router,
        candidate_router,
        health_router,
        identity_router,
        interview_router,
        offer_router,
        organization_router,
        reporting_router,
        retention_router,
        webhook_router,
        webhook_commands,
    ):
        app.include_router(router)
    install_webhook_openapi(app)
    return app


app = create_app()
