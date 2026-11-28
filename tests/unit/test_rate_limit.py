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


def test_careers_ip_and_email_windows_reset_independently(monkeypatch):
    from app.shared.rate_limit import MemoryFixedWindowRateLimiter

    now = [100.0]
    monkeypatch.setattr("app.shared.rate_limit.time.monotonic", lambda: now[0])
    limiter = MemoryFixedWindowRateLimiter()
    for _ in range(5):
        assert limiter.consume("talentflow:careers:ip:demo", limit=5, window_seconds=3600).allowed
    assert not limiter.consume("talentflow:careers:ip:demo", limit=5, window_seconds=3600).allowed
    for _ in range(3):
        assert limiter.consume(
            "talentflow:careers:email:hash", limit=3, window_seconds=86400
        ).allowed
    assert not limiter.consume(
        "talentflow:careers:email:hash", limit=3, window_seconds=86400
    ).allowed
    now[0] += 3599.999
    assert not limiter.consume("talentflow:careers:ip:demo", limit=5, window_seconds=3600).allowed
    now[0] += 0.001
    assert limiter.consume("talentflow:careers:ip:demo", limit=5, window_seconds=3600).allowed
    assert not limiter.consume(
        "talentflow:careers:email:hash", limit=3, window_seconds=86400
    ).allowed
    now[0] = 86500.0
    assert limiter.consume("talentflow:careers:email:hash", limit=3, window_seconds=86400).allowed
