from app.shared.rate_limit import MemoryFixedWindowRateLimiter


def test_memory_rate_limiter_rejects_after_limit_within_window() -> None:
    limiter = MemoryFixedWindowRateLimiter()

    first = limiter.consume("client", limit=2, window_seconds=60)
    second = limiter.consume("client", limit=2, window_seconds=60)
    rejected = limiter.consume("client", limit=2, window_seconds=60)

    assert first.allowed is True
    assert first.remaining == 1
    assert second.allowed is True
    assert second.remaining == 0
    assert rejected.allowed is False
    assert rejected.retry_after >= 1
