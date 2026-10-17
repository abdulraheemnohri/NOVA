from nova.security import LocalRateLimiter


def test_sliding_window_allows_limit_then_blocks_and_recovers():
    limiter = LocalRateLimiter(requests_per_minute=2, block_seconds=5)
    assert limiter.allow("client", now=10)
    assert limiter.allow("client", now=11)
    assert not limiter.allow("client", now=12)
    assert not limiter.allow("client", now=16)
    # Requests remain in the 60-second sliding window after the temporary block.
    assert limiter.allow("client", now=72)


def test_failed_authentication_has_independent_budget():
    limiter = LocalRateLimiter(failed_auth_attempts=2, block_seconds=5)
    limiter.record_auth_failure("client", now=10)
    assert not limiter.auth_blocked("client", now=10)
    limiter.record_auth_failure("client", now=11)
    assert limiter.auth_blocked("client", now=12)
    assert not limiter.auth_blocked("client", now=17)


def test_clients_have_independent_buckets():
    limiter = LocalRateLimiter(requests_per_minute=1)
    assert limiter.allow("first", now=1)
    assert limiter.allow("second", now=1)
    assert not limiter.allow("first", now=2)
