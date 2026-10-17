"""Persistent local task queue for NOVA.

Stores operator-authored tasks and lifecycle state. It deliberately does not execute
shell commands or claim to be an autonomous scheduler; execution adapters must be
added behind the policy and approval layer.
"""
from __future__ import annotations
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from nova.audit import append_audit
from nova.config import settings

router = APIRouter(prefix="/api/tasks", tags=["task planning"])
STATUSES = {"queued", "planned", "in_progress", "completed", "failed", "cancelled"}
TRANSITIONS = {
    "queued": {"planned", "cancelled"},
    "planned": {"queued", "in_progress", "cancelled"},
    "in_progress": {"completed", "failed", "cancelled"},
    "failed": {"queued", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}

def _connect() -> sqlite3.Connection:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(settings.database_path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=10000")
    con.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'queued', priority TEXT NOT NULL DEFAULT 'normal',
        due_at TEXT, plan_json TEXT NOT NULL DEFAULT '[]', result TEXT,
        attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    con.commit()
    return con

def _parse_due(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(422, "due_at must be an ISO-8601 date/time.") from exc
    if parsed.tzinfo is None:
        raise HTTPException(422, "due_at must include a timezone, for example Z or +05:00.")
    return parsed.astimezone(timezone.utc).isoformat()

class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    due_at: str | None = Field(default=None, max_length=80)
    plan: list[str] = Field(default_factory=list, max_length=50)

class TaskStatusUpdate(BaseModel):
    status: Literal["queued", "planned", "in_progress", "completed", "failed", "cancelled"]
    result: str | None = Field(default=None, max_length=20000)

@router.get("")
def list_tasks(status: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500)):
    if status is not None and status not in STATUSES:
        raise HTTPException(422, "Unknown task status.")
    con = _connect()
    try:
        rows = (con.execute("SELECT * FROM tasks WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit)).fetchall()
                if status else con.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall())
        result = []
        for row in rows:
            item = dict(row)
            item["plan"] = json.loads(item.pop("plan_json"))
            result.append(item)
        return result
    finally:
        con.close()

@router.post("", status_code=201)
def create_task(req: TaskCreate):
    title = req.title.strip()
    if not title:
        raise HTTPException(422, "Task title cannot be blank.")
    if any(not step.strip() or len(step) > 1000 for step in req.plan):
        raise HTTPException(422, "Each plan step must contain 1–1000 characters.")
    due_at = _parse_due(req.due_at)
    now = datetime.now(timezone.utc).isoformat()
    task_id = str(uuid.uuid4())
    con = _connect()
    try:
        con.execute(
            "INSERT INTO tasks(id,title,description,status,priority,due_at,plan_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (task_id, title, req.description.strip(), "queued", req.priority, due_at,
             json.dumps([step.strip() for step in req.plan]), now, now),
        )
        con.commit()
        row = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        item = dict(row)
        item["plan"] = json.loads(item.pop("plan_json"))
    finally:
        con.close()
    append_audit(settings.audit_path, "task.created", {
        "task_id": task_id, "priority": req.priority, "has_due_at": due_at is not None,
        "plan_steps": len(req.plan),
    })
    return item

@router.post("/{task_id}/status")
def update_task_status(task_id: str, req: TaskStatusUpdate):
    con = _connect()
    try:
        row = con.execute("SELECT status, attempts FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Task not found.")
        old_status = str(row["status"])
        if req.status == old_status:
            return {"id": task_id, "status": old_status, "unchanged": True}
        if req.status not in TRANSITIONS[old_status]:
            raise HTTPException(409, f"Invalid task transition: {old_status} -> {req.status}.")
        now = datetime.now(timezone.utc).isoformat()
        attempts = int(row["attempts"]) + (1 if req.status == "in_progress" else 0)
        con.execute(
            "UPDATE tasks SET status=?, result=COALESCE(?, result), attempts=?, updated_at=? WHERE id=? AND status=?",
            (req.status, req.result, attempts, now, task_id, old_status),
        )
        con.commit()
    finally:
        con.close()
    append_audit(settings.audit_path, "task.status_changed", {"task_id": task_id, "from": old_status, "to": req.status})
    return {"id": task_id, "status": req.status, "attempts": attempts}

@router.delete("/{task_id}")
def delete_task(task_id: str):
    con = _connect()
    try:
        row = con.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Task not found.")
        if row["status"] == "in_progress":
            raise HTTPException(409, "Cancel an in-progress task before deleting it.")
        con.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        con.commit()
    finally:
        con.close()
    append_audit(settings.audit_path, "task.deleted", {"task_id": task_id})
    return {"deleted": True, "id": task_id}
