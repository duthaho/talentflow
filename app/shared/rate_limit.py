from __future__ import annotations

import ipaddress
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import FastAPI, Request
from redis import Redis
from starlette.responses import JSONResponse, Response

from app.shared.observability import rate_limit_rejections

_EXEMPT_PATHS = {"/health", "/health/live", "/health/ready", "/metrics", "/docs", "/openapi.json"}


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after: int


class MemoryFixedWindowRateLimiter:
    def __init__(self) -> None:
        self._windows: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def consume(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        now = time.monotonic()
        with self._lock:
            count, expires_at = self._windows.get(key, (0, now + window_seconds))
            if expires_at <= now:
                count, expires_at = 0, now + window_seconds
            count += 1
            self._windows[key] = (count, expires_at)
        return RateLimitDecision(
            count <= limit, max(0, limit - count), max(1, int(expires_at - now))
        )

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        return None


class RedisFixedWindowRateLimiter:
    _CONSUME = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""

    def __init__(self, url: str) -> None:
        self._redis = Redis.from_url(
            url, decode_responses=False, socket_connect_timeout=2, socket_timeout=2
        )

    def consume(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        count, ttl = self._redis.eval(self._CONSUME, 1, key, window_seconds)
        retry_after = max(1, int(ttl))
        return RateLimitDecision(int(count) <= limit, max(0, limit - int(count)), retry_after)

    def ping(self) -> bool:
        return bool(self._redis.ping())

    def close(self) -> None:
        self._redis.close()


def client_identifier(request: Request, trusted_proxy_cidrs: tuple[str, ...]) -> str:
    peer = request.client.host if request.client else "unknown"
    trusted_networks = tuple(ipaddress.ip_network(cidr) for cidr in trusted_proxy_cidrs)
    try:
        peer_is_trusted = any(ipaddress.ip_address(peer) in network for network in trusted_networks)
    except ValueError:
        peer_is_trusted = False
    if peer_is_trusted:
        forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return peer


def install_rate_limit_middleware(
    app: FastAPI,
    *,
    limiter: MemoryFixedWindowRateLimiter | RedisFixedWindowRateLimiter,
    enabled: bool,
    requests_per_minute: int,
    trusted_proxy_cidrs: tuple[str, ...],
) -> None:
    @app.middleware("http")
    async def rate_limit(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not enabled or request.method == "OPTIONS" or request.url.path in _EXEMPT_PATHS:
            return await call_next(request)
        decision = limiter.consume(
            f"talentflow:rate-limit:{client_identifier(request, trusted_proxy_cidrs)}",
            limit=requests_per_minute,
            window_seconds=60,
        )
        headers = {
            "X-RateLimit-Limit": str(requests_per_minute),
            "X-RateLimit-Remaining": str(decision.remaining),
            "X-RateLimit-Reset": str(decision.retry_after),
        }
        if not decision.allowed:
            rate_limit_rejections.inc()
            headers["Retry-After"] = str(decision.retry_after)
            return JSONResponse(
                status_code=429, content={"detail": "Rate limit exceeded"}, headers=headers
            )
        response = await call_next(request)
        response.headers.update(headers)
        return response
