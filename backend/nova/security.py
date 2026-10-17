"""Small, process-local API abuse controls for NOVA.

These controls are defense in depth, not a replacement for a reverse proxy or
OS firewall in multi-worker/multi-user deployments. No forwarded IP headers are
trusted because the service is intended to bind to loopback.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class _Bucket:
    events: deque[float] = field(default_factory=deque)
    blocked_until: float = 0.0


class LocalRateLimiter:
    """Thread-safe sliding-window limiter with a separate failed-auth budget."""

    def __init__(
        self,
        *,
        requests_per_minute: int = 120,
        failed_auth_attempts: int = 10,
        failed_auth_window_seconds: int = 300,
        block_seconds: int = 60,
    ) -> None:
        if min(requests_per_minute, failed_auth_attempts, failed_auth_window_seconds, block_seconds) < 1:
            raise ValueError("Rate-limiter limits must be positive.")
        self.requests_per_minute = requests_per_minute
        self.failed_auth_attempts = failed_auth_attempts
        self.failed_auth_window_seconds = failed_auth_window_seconds
        self.block_seconds = block_seconds
        self._requests: dict[str, _Bucket] = {}
        self._failures: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _prune(bucket: _Bucket, cutoff: float) -> None:
        while bucket.events and bucket.events[0] <= cutoff:
            bucket.events.popleft()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._requests.setdefault(key, _Bucket())
            self._prune(bucket, now - 60)
            if bucket.blocked_until > now or len(bucket.events) >= self.requests_per_minute:
                bucket.blocked_until = max(bucket.blocked_until, now + self.block_seconds)
                return False
            bucket.events.append(now)
            if len(self._requests) > 4096:
                self._requests = {
                    k: v for k, v in self._requests.items()
                    if (v.events and v.events[-1] > now - 600) or v.blocked_until > now
                }
            return True

    def record_auth_failure(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._failures.setdefault(key, _Bucket())
            self._prune(bucket, now - self.failed_auth_window_seconds)
            bucket.events.append(now)
            if len(bucket.events) >= self.failed_auth_attempts:
                bucket.blocked_until = max(bucket.blocked_until, now + self.block_seconds)
            if len(self._failures) > 4096:
                self._failures = {
                    k: v for k, v in self._failures.items()
                    if (v.events and v.events[-1] > now - self.failed_auth_window_seconds)
                    or v.blocked_until > now
                }

    def auth_blocked(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._failures.get(key)
            if bucket is None:
                return False
            self._prune(bucket, now - self.failed_auth_window_seconds)
            if bucket.blocked_until <= now:
                bucket.blocked_until = 0.0
                return False
            return True
