"""Lease-based local scheduler for due NOVA tasks.

The scheduler only moves due, operator-authored tasks from queued to planned.
It never executes shell commands, generated plans, or external tools. The planned
state is an explicit human-review handoff, not a claim that work was executed.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter
from nova.audit import append_audit
from nova.config import settings
from nova.tasks import _connect as _tasks_connect

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])
MAX_ATTEMPTS = 5
LEASE_SECONDS = 60
_worker_lock = threading.Lock()
_worker_thread: threading.Thread | None = None
_worker_stop = threading.Event()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_columns(con) -> None:
    existing = {row["name"] for row in con.execute("PRAGMA table_info(tasks)").fetchall()}
    migrations = {
        "scheduler_claimed_until": "TEXT",
        "scheduler_claimed_by": "TEXT",
        "scheduler_attempts": "INTEGER NOT NULL DEFAULT 0",
        "scheduler_last_error": "TEXT",
    }
    for name, definition in migrations.items():
        if name not in existing:
            con.execute(f"ALTER TABLE tasks ADD COLUMN {name} {definition}")


def scheduler_status() -> dict[str, Any]:
    con = _tasks_connect()
    try:
        _ensure_columns(con)
        now = _now().isoformat()
        due = con.execute(
            "SELECT count(*) FROM tasks WHERE status='queued' AND due_at IS NOT NULL AND due_at<=?",
            (now,),
        ).fetchone()[0]
        leased = con.execute(
            "SELECT count(*) FROM tasks WHERE scheduler_claimed_until IS NOT NULL AND scheduler_claimed_until>?",
            (now,),
        ).fetchone()[0]
        return {
            "enabled": bool(settings.scheduler_enabled),
            "worker_running": bool(_worker_thread and _worker_thread.is_alive()),
            "interval_seconds": settings.scheduler_interval_seconds,
            "due_tasks_waiting": int(due),
            "active_leases": int(leased),
            "max_attempts": MAX_ATTEMPTS,
            "lease_seconds": LEASE_SECONDS,
            "execution_mode": "due tasks become planned for human review; no tools or commands execute",
        }
    finally:
        con.close()


def run_due_tasks(limit: int = 50) -> dict[str, Any]:
    """Claim due tasks atomically and dispatch them to planned/human-review state."""
    now_dt = _now()
    now = now_dt.isoformat()
    lease_until = (now_dt + timedelta(seconds=LEASE_SECONDS)).isoformat()
    worker_id = str(uuid.uuid4())
    claimed: list[dict[str, str]] = []
    con = _tasks_connect()
    try:
        _ensure_columns(con)
        con.execute("BEGIN IMMEDIATE")
        rows = con.execute(
            """SELECT id,title FROM tasks
               WHERE status='queued' AND due_at IS NOT NULL AND due_at<=?
                 AND (scheduler_claimed_until IS NULL OR scheduler_claimed_until<=?)
                 AND scheduler_attempts < ?
               ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
                                      WHEN 'normal' THEN 2 ELSE 3 END, due_at ASC
               LIMIT ?""",
            (now, now, MAX_ATTEMPTS, max(1, min(limit, 200))),
        ).fetchall()
        for row in rows:
            changed = con.execute(
                """UPDATE tasks SET scheduler_claimed_until=?, scheduler_claimed_by=?,
                   scheduler_attempts=scheduler_attempts+1, scheduler_last_error=NULL
                   WHERE id=? AND status='queued'
                     AND (scheduler_claimed_until IS NULL OR scheduler_claimed_until<=?)""",
                (lease_until, worker_id, row["id"], now),
            )
            if changed.rowcount == 1:
                claimed.append({"id": row["id"], "title": row["title"]})
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    planned: list[str] = []
    failures: list[str] = []
    for item in claimed:
        con = _tasks_connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            changed = con.execute(
                """UPDATE tasks SET status='planned', updated_at=?,
                   scheduler_claimed_until=NULL, scheduler_claimed_by=NULL
                   WHERE id=? AND status='queued' AND scheduler_claimed_by=?""",
                (_now().isoformat(), item["id"], worker_id),
            )
            con.commit()
            if changed.rowcount:
                planned.append(item["id"])
        except Exception as exc:
            con.rollback()
            failures.append(item["id"])
            con.execute("BEGIN IMMEDIATE")
            current = con.execute(
                "SELECT scheduler_attempts FROM tasks WHERE id=? AND scheduler_claimed_by=?",
                (item["id"], worker_id),
            ).fetchone()
            if current:
                exhausted = int(current["scheduler_attempts"]) >= MAX_ATTEMPTS
                con.execute(
                    """UPDATE tasks SET status=?, scheduler_claimed_until=NULL,
                       scheduler_claimed_by=NULL, scheduler_last_error=?, updated_at=?
                       WHERE id=? AND scheduler_claimed_by=?""",
                    ("failed" if exhausted else "queued", type(exc).__name__, _now().isoformat(),
                     item["id"], worker_id),
                )
            con.commit()
        finally:
            con.close()
    for task_id in planned:
        append_audit(settings.audit_path, "scheduler.task_planned", {
            "task_id": task_id, "worker_id": worker_id, "human_review_required": True,
        })
    for task_id in failures:
        append_audit(settings.audit_path, "scheduler.task_dispatch_failed", {
            "task_id": task_id, "worker_id": worker_id,
        })
    return {
        "claimed": len(claimed),
        "planned": planned,
        "failed_dispatch": failures,
        "message": "Planned tasks require operator review; no command or tool was executed.",
    }


@router.get("/status")
def get_scheduler_status():
    return scheduler_status()


@router.post("/run-once")
def run_scheduler_once():
    result = run_due_tasks()
    append_audit(settings.audit_path, "scheduler.run_once", {
        "claimed": result["claimed"], "planned_count": len(result["planned"]),
        "failed_count": len(result["failed_dispatch"]),
    })
    return {**result, "status": scheduler_status()}


def _worker_loop() -> None:
    while not _worker_stop.is_set():
        try:
            run_due_tasks()
        except Exception as exc:
            # Never crash the API process because an optional background worker failed.
            try:
                append_audit(settings.audit_path, "scheduler.worker_error", {
                    "error_type": type(exc).__name__,
                })
            except Exception:
                pass
        _worker_stop.wait(max(5, int(settings.scheduler_interval_seconds)))


def start_worker() -> bool:
    global _worker_thread
    if not settings.scheduler_enabled:
        return False
    with _worker_lock:
        if _worker_thread and _worker_thread.is_alive():
            return True
        _worker_stop.clear()
        _worker_thread = threading.Thread(target=_worker_loop, name="nova-scheduler", daemon=True)
        _worker_thread.start()
    return True


def stop_worker() -> None:
    global _worker_thread
    _worker_stop.set()
    with _worker_lock:
        thread = _worker_thread
    if thread and thread.is_alive():
        thread.join(timeout=2)
    with _worker_lock:
        if _worker_thread is thread:
            _worker_thread = None
