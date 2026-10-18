from concurrent.futures import ThreadPoolExecutor
import sqlite3

from nova.security import PersistentRateLimiter


def test_rate_budget_is_shared_across_concurrent_requests(tmp_path):
    database = tmp_path / "rate-limit.sqlite3"
    limit = PersistentRateLimiter(
        lambda: database,
        requests_per_minute=5,
        failed_auth_attempts=3,
        block_seconds=30,
    )

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: limit.allow("127.0.0.1", now=1000.0), range(12)))

    assert sum(results) == 5


def test_auth_failures_and_blocks_survive_limiter_recreation(tmp_path):
    database = tmp_path / "rate-limit.sqlite3"
    first = PersistentRateLimiter(
        lambda: database,
        failed_auth_attempts=3,
        failed_auth_window_seconds=300,
        block_seconds=30,
    )
    for _ in range(3):
        first.record_auth_failure("127.0.0.1", now=1000.0)

    second = PersistentRateLimiter(
        lambda: database,
        failed_auth_attempts=3,
        failed_auth_window_seconds=300,
        block_seconds=30,
    )
    assert second.auth_blocked("127.0.0.1", now=1001.0)
    assert not second.auth_blocked("127.0.0.1", now=1031.0)


def test_expired_rate_limit_blocks_are_cleaned_up(tmp_path):
    database = tmp_path / "rate-limit.sqlite3"
    limit = PersistentRateLimiter(
        lambda: database,
        requests_per_minute=1,
        block_seconds=30,
    )
    assert limit.allow("client", now=1000.0)
    assert not limit.allow("client", now=1000.0)
    assert limit.allow("client", now=1061.0)

    with sqlite3.connect(database) as con:
        remaining = con.execute(
            "SELECT count(*) FROM nova_rate_blocks WHERE kind='request'"
        ).fetchone()[0]
    assert remaining == 0
