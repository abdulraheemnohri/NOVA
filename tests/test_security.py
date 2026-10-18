from nova.security import LocalRateLimiter, PersistentRateLimiter


def test_sliding_window_allows_limit_then_blocks_and_recovers():
    limiter = LocalRateLimiter(requests_per_minute=2, block_seconds=5)
    assert limiter.allow("client", now=10)
    assert limiter.allow("client", now=11)
    assert not limiter.allow("client", now=12)
    assert not limiter.allow("client", now=16)
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


def test_persistent_limiter_survives_new_instance(tmp_path):
    path = tmp_path / "nova.sqlite3"
    first = PersistentRateLimiter(lambda: path, requests_per_minute=1, block_seconds=5)
    assert first.allow("client", now=100)
    assert not first.allow("client", now=101)
    restarted = PersistentRateLimiter(lambda: path, requests_per_minute=1, block_seconds=5)
    assert not restarted.allow("client", now=102)
    assert restarted.allow("client", now=106)


def test_persistent_failed_auth_budget_survives_restart(tmp_path):
    path = tmp_path / "nova.sqlite3"
    first = PersistentRateLimiter(lambda: path, failed_auth_attempts=2, block_seconds=5)
    first.record_auth_failure("client", now=100)
    first.record_auth_failure("client", now=101)
    restarted = PersistentRateLimiter(lambda: path, failed_auth_attempts=2, block_seconds=5)
    assert restarted.auth_blocked("client", now=102)
    assert not restarted.auth_blocked("client", now=106)


def test_persistent_limiter_does_not_store_raw_client_key(tmp_path):
    path = tmp_path / "nova.sqlite3"
    limiter = PersistentRateLimiter(lambda: path)
    limiter.allow("192.0.2.1", now=100)
    import sqlite3
    con = sqlite3.connect(path)
    try:
        rows = con.execute("SELECT DISTINCT client_key FROM api_rate_events").fetchall()
    finally:
        con.close()
    assert rows
    assert "192.0.2.1" not in rows[0][0]
