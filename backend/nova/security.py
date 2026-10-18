"""API abuse controls for NOVA.

LocalRateLimiter is an in-memory option for tests. PersistentRateLimiter stores
sliding-window events in SQLite so counters survive restarts and are shared by
workers using the same database file. A trusted edge limiter is still required
for hostile multi-host deployments.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from nova.config import settings


@dataclass
class _Bucket:
    events: deque[float] = field(default_factory=deque)
    blocked_until: float = 0.0


class LocalRateLimiter:
    """Thread-safe process-local sliding-window limiter with auth-failure budget."""

    def __init__(self, *, requests_per_minute=120, failed_auth_attempts=10,
                 failed_auth_window_seconds=300, block_seconds=60):
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
    def _prune(bucket: _Bucket, cutoff: float):
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
                self._requests = {k: v for k, v in self._requests.items()
                                  if (v.events and v.events[-1] > now - 600) or v.blocked_until > now}
            return True

    def record_auth_failure(self, key: str, now: float | None = None):
        now = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._failures.setdefault(key, _Bucket())
            self._prune(bucket, now - self.failed_auth_window_seconds)
            bucket.events.append(now)
            if len(bucket.events) >= self.failed_auth_attempts:
                bucket.blocked_until = max(bucket.blocked_until, now + self.block_seconds)
            if len(self._failures) > 4096:
                self._failures = {k: v for k, v in self._failures.items()
                                  if (v.events and v.events[-1] > now - self.failed_auth_window_seconds)
                                  or v.blocked_until > now}

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


class PersistentRateLimiter:
    """SQLite-backed limiter. Uses wall-clock epochs because events survive restarts."""

    def __init__(self, path_provider: Callable[[], Path] | None = None, *,
                 requests_per_minute=120, failed_auth_attempts=10,
                 failed_auth_window_seconds=300, block_seconds=60):
        if min(requests_per_minute, failed_auth_attempts, failed_auth_window_seconds, block_seconds) < 1:
            raise ValueError("Rate-limiter limits must be positive.")
        self._path_provider = path_provider or (lambda: settings.database_path)
        self.requests_per_minute = requests_per_minute
        self.failed_auth_attempts = failed_auth_attempts
        self.failed_auth_window_seconds = failed_auth_window_seconds
        self.block_seconds = block_seconds
        self._lock = threading.Lock()

    @staticmethod
    def _key(key: str) -> str:
        # Avoid retaining raw peer addresses in the persistent limiter database.
        return hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()

    def _db(self):
        path = self._path_provider()
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, timeout=10, isolation_level=None)
        con.execute("PRAGMA busy_timeout=10000")
        con.execute("""CREATE TABLE IF NOT EXISTS api_rate_events(
            client_key TEXT NOT NULL, category TEXT NOT NULL, occurred_at REAL NOT NULL)""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_api_rate_events_lookup ON api_rate_events(client_key,category,occurred_at)")
        con.execute("""CREATE TABLE IF NOT EXISTS api_rate_blocks(
            client_key TEXT NOT NULL, category TEXT NOT NULL, blocked_until REAL NOT NULL,
            PRIMARY KEY(client_key,category))""")
        return con

    def _blocked(self, key: str, category: str, now: float) -> bool:
        con = self._db()
        try:
            row = con.execute("SELECT blocked_until FROM api_rate_blocks WHERE client_key=? AND category=?",
                              (self._key(key), category)).fetchone()
            return bool(row and row[0] > now)
        finally:
            con.close()

    def auth_blocked(self, key: str, now: float | None = None) -> bool:
        return self._blocked(key, "auth", time.time() if now is None else now)

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        client = self._key(key)
        with self._lock:
            con = self._db()
            try:
                con.execute("BEGIN IMMEDIATE")
                con.execute("DELETE FROM api_rate_events WHERE occurred_at<=?", (now - max(60, self.failed_auth_window_seconds),))
                row = con.execute("SELECT blocked_until FROM api_rate_blocks WHERE client_key=? AND category='request'",
                                  (client,)).fetchone()
                count = con.execute("SELECT COUNT(*) FROM api_rate_events WHERE client_key=? AND category='request' AND occurred_at>?",
                                    (client, now - 60)).fetchone()[0]
                if (row and row[0] > now) or count >= self.requests_per_minute:
                    con.execute("INSERT INTO api_rate_blocks VALUES(?,?,?) ON CONFLICT(client_key,category) DO UPDATE SET blocked_until=MAX(blocked_until,excluded.blocked_until)",
                                (client, "request", now + self.block_seconds))
                    con.commit()
                    return False
                con.execute("INSERT INTO api_rate_events VALUES(?,?,?)", (client, "request", now))
                con.commit()
                return True
            except Exception:
                con.rollback()
                raise
            finally:
                con.close()

    def record_auth_failure(self, key: str, now: float | None = None):
        now = time.time() if now is None else now
        client = self._key(key)
        with self._lock:
            con = self._db()
            try:
                con.execute("BEGIN IMMEDIATE")
                cutoff = now - self.failed_auth_window_seconds
                con.execute("DELETE FROM api_rate_events WHERE client_key=? AND category='auth' AND occurred_at<=?",
                            (client, cutoff))
                con.execute("INSERT INTO api_rate_events VALUES(?,?,?)", (client, "auth", now))
                count = con.execute("SELECT COUNT(*) FROM api_rate_events WHERE client_key=? AND category='auth' AND occurred_at>?",
                                    (client, cutoff)).fetchone()[0]
                if count >= self.failed_auth_attempts:
                    con.execute("INSERT INTO api_rate_blocks VALUES(?,?,?) ON CONFLICT(client_key,category) DO UPDATE SET blocked_until=MAX(blocked_until,excluded.blocked_until)",
                                (client, "auth", now + self.block_seconds))
                con.commit()
            except Exception:
                con.rollback()
                raise
            finally:
                con.close()



class PersistentRateLimiter:
    """SQLite-backed sliding-window limiter shared by processes using one database.

    Uses wall-clock timestamps because monotonic clocks are not stable across
    process restarts. Database writes are serialized with BEGIN IMMEDIATE so
    simultaneous workers cannot all pass the same request budget.
    """

    def __init__(
        self,
        database_path,
        *,
        requests_per_minute: int = 120,
        failed_auth_attempts: int = 10,
        failed_auth_window_seconds: int = 300,
        block_seconds: int = 60,
    ) -> None:
        if min(requests_per_minute, failed_auth_attempts, failed_auth_window_seconds, block_seconds) < 1:
            raise ValueError("Rate-limiter limits must be positive.")
        self._database_path = database_path
        self.requests_per_minute = requests_per_minute
        self.failed_auth_attempts = failed_auth_attempts
        self.failed_auth_window_seconds = failed_auth_window_seconds
        self.block_seconds = block_seconds

    def _connect(self):
        import sqlite3

        path = self._database_path() if callable(self._database_path) else self._database_path
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, timeout=10, isolation_level=None)
        con.execute("PRAGMA busy_timeout=10000")
        con.execute("""CREATE TABLE IF NOT EXISTS nova_rate_events(
            kind TEXT NOT NULL, bucket_key TEXT NOT NULL, event_at REAL NOT NULL)""")
        con.execute("""CREATE INDEX IF NOT EXISTS idx_nova_rate_events_lookup
            ON nova_rate_events(kind, bucket_key, event_at)""")
        con.execute("""CREATE TABLE IF NOT EXISTS nova_rate_blocks(
            kind TEXT NOT NULL, bucket_key TEXT NOT NULL, blocked_until REAL NOT NULL,
            PRIMARY KEY(kind, bucket_key))""")
        return con

    def _blocked(self, con, kind: str, key: str, now: float) -> bool:
        row = con.execute(
            "SELECT blocked_until FROM nova_rate_blocks WHERE kind=? AND bucket_key=?",
            (kind, key),
        ).fetchone()
        return bool(row and row[0] > now)

    def auth_blocked(self, key: str, now: float | None = None) -> bool:
        import time
        now = time.time() if now is None else now
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute("DELETE FROM nova_rate_events WHERE kind='auth' AND event_at<=?",
                        (now - self.failed_auth_window_seconds,))
            blocked = self._blocked(con, "auth", key, now)
            if not blocked:
                con.execute("DELETE FROM nova_rate_blocks WHERE kind='auth' AND bucket_key=?",
                            (key,))
            con.commit()
            return blocked
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def allow(self, key: str, now: float | None = None) -> bool:
        import time
        now = time.time() if now is None else now
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute("DELETE FROM nova_rate_events WHERE kind='request' AND event_at<=?",
                        (now - 60,))
            count = con.execute(
                "SELECT COUNT(*) FROM nova_rate_events WHERE kind='request' AND bucket_key=? AND event_at>?",
                (key, now - 60),
            ).fetchone()[0]
            blocked = self._blocked(con, "request", key, now)
            if blocked or count >= self.requests_per_minute:
                con.execute("""INSERT INTO nova_rate_blocks(kind,bucket_key,blocked_until)
                    VALUES('request',?,?) ON CONFLICT(kind,bucket_key) DO UPDATE SET
                    blocked_until=MAX(blocked_until,excluded.blocked_until)""",
                    (key, now + self.block_seconds))
                con.commit()
                return False
            con.execute("INSERT INTO nova_rate_events(kind,bucket_key,event_at) VALUES('request',?,?)",
                        (key, now))
            con.commit()
            return True
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def record_auth_failure(self, key: str, now: float | None = None) -> None:
        import time
        now = time.time() if now is None else now
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            cutoff = now - self.failed_auth_window_seconds
            con.execute("DELETE FROM nova_rate_events WHERE kind='auth' AND event_at<=?", (cutoff,))
            con.execute("INSERT INTO nova_rate_events(kind,bucket_key,event_at) VALUES('auth',?,?)",
                        (key, now))
            count = con.execute(
                "SELECT COUNT(*) FROM nova_rate_events WHERE kind='auth' AND bucket_key=? AND event_at>?",
                (key, cutoff),
            ).fetchone()[0]
            if count >= self.failed_auth_attempts:
                con.execute("""INSERT INTO nova_rate_blocks(kind,bucket_key,blocked_until)
                    VALUES('auth',?,?) ON CONFLICT(kind,bucket_key) DO UPDATE SET
                    blocked_until=MAX(blocked_until,excluded.blocked_until)""",
                    (key, now + self.block_seconds))
            # Bound stale state so client keys cannot grow the database indefinitely.
            con.execute("DELETE FROM nova_rate_blocks WHERE blocked_until<=?", (now,))
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()
