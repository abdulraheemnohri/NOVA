from __future__ import annotations

import hashlib
import json
import os
import secrets
import hmac
import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from nova.audit import append_audit, verify_audit
from nova.config import settings
from nova.knowledge import initialize_knowledge, router as knowledge_router
from nova.litert import LiteRTError, chat, health
from nova.model_manager import active_model_id, router as model_router
from nova.huggingface import router as huggingface_router
from nova.policy import evaluate_tool

app = FastAPI(title="NOVA — Neural Offline Verified Agent", version="0.1.0")


@app.middleware("http")
async def require_local_api_token(request: Request, call_next):
    # Health is intentionally public for local process supervision; all other API routes
    # require the generated, file-backed bearer token.
    if request.url.path == "/api/health" or not request.url.path.startswith("/api/"):
        return await call_next(request)
    try:
        expected = settings.api_token_file.read_text(encoding="utf-8").strip()
    except OSError:
        expected = ""
    auth = request.headers.get("authorization", "")
    supplied = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        return JSONResponse(status_code=401, content={"detail": "Local API token required or invalid."})
    # Fail closed before any API handler can mutate state if the audit chain is damaged.
    # Keep health and the explicit verification endpoint available for diagnosis.
    if request.url.path not in {"/api/health", "/api/audit/verify"}:
        valid, _ = verify_audit(settings.audit_path)
        if not valid:
            return JSONResponse(
                status_code=503,
                content={"detail": "Audit integrity failure; API actions are disabled until an operator investigates."},
            )
    return await call_next(request)
app.include_router(knowledge_router)
app.include_router(model_router)
app.include_router(huggingface_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    max_tokens: int = Field(default=512, ge=1, le=4096)


class ApprovalRequest(BaseModel):
    action: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=1000)


class FileWriteRequest(BaseModel):
    relative_path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=1000000)
    approval_id: str | None = None


class RollbackRequest(BaseModel):
    snapshot_id: str = Field(min_length=1, max_length=80)
    approval_id: str = Field(min_length=1, max_length=80)


def _db():
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(settings.database_path)
    con.row_factory = sqlite3.Row
    con.execute(
        """CREATE TABLE IF NOT EXISTS approvals(
        id TEXT PRIMARY KEY, action TEXT NOT NULL, payload_json TEXT NOT NULL,
        reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, decided_at TEXT)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS snapshots(
        id TEXT PRIMARY KEY, relative_path TEXT NOT NULL, existed INTEGER NOT NULL,
        backup_path TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        rolled_back_at TEXT)"""
    )
    con.commit()
    return con


def _audit(event: str, details: dict[str, Any]):
    append_audit(settings.audit_path, event, details)


def _safe_path(relative: str) -> Path:
    # Reject absolute paths and traversal before resolving symlinks.
    candidate = Path(relative)
    if candidate.is_absolute() or any(part in {"..", ""} for part in candidate.parts):
        raise HTTPException(403, "Path must be relative and remain inside the workspace.")
    # Snapshot backups are internal recovery state, never ordinary user workspace files.
    if candidate.parts and candidate.parts[0] == ".nova-snapshots":
        raise HTTPException(403, "The internal snapshot store is reserved and cannot be accessed as a workspace path.")
    root = settings.workspace.resolve()
    # Do not follow user-controlled symlinks, even if their current destination is
    # still inside the workspace. This reduces symlink escape and aliasing risks.
    # A production multi-user deployment should additionally use dirfd/openat-style
    # operations to eliminate races between validation and filesystem mutation.
    cursor = root
    for part in candidate.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise HTTPException(403, "Workspace paths must not contain symbolic links.")
    target = (root / candidate).resolve()
    if target == root or root not in target.parents:
        raise HTTPException(403, "Path escapes workspace.")
    return target


def _atomic_write(target: Path, content: bytes):
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".nova-write-", dir=target.parent, delete=False
        ) as stream:
            temp_name = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


@app.on_event("startup")
def startup():
    settings.workspace.mkdir(parents=True, exist_ok=True)
    settings.api_token_file.parent.mkdir(parents=True, exist_ok=True)
    if not settings.api_token_file.exists():
        token = secrets.token_urlsafe(32)
        fd = os.open(settings.api_token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(token + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    try:
        os.chmod(settings.api_token_file, 0o600)
    except OSError:
        pass
    con = _db()
    con.close()
    initialize_knowledge()


@app.get("/api/health")
def api_health():
    valid, count = verify_audit(settings.audit_path)
    return {
        "status": "ok",
        "offline_mode": True,
        "llm_runtime": "LiteRT-LM only",
        "litert": health(),
        "audit_chain_valid": valid,
        "audit_event_count": count,
    }


@app.post("/api/chat")
def api_chat(req: ChatRequest):
    _audit("chat.request", {"message_sha256": hashlib.sha256(req.message.encode()).hexdigest()})
    try:
        model_id = active_model_id()
        answer = chat(req.message, req.max_tokens, model_id=model_id)
    except LiteRTError as exc:
        _audit("chat.failure", {"error": str(exc)})
        raise HTTPException(503, str(exc)) from exc
    _audit("chat.response", {"answer_sha256": hashlib.sha256(answer.encode()).hexdigest()})
    return {"answer": answer, "model": model_id, "runtime": "LiteRT-LM"}


@app.get("/api/approvals")
def list_approvals():
    con = _db()
    try:
        rows = con.execute("SELECT * FROM approvals ORDER BY created_at DESC").fetchall()
    finally:
        con.close()
    return [dict(row) for row in rows]


@app.post("/api/approvals")
def create_approval(req: ApprovalRequest):
    policy = evaluate_tool(req.action)
    if not policy.requires_approval:
        _audit("approval.blocked", {"action": req.action, "reason": policy.reason})
        raise HTTPException(403, policy.reason)
    approval_id = str(uuid.uuid4())
    payload_json = json.dumps(req.payload, sort_keys=True)
    con = _db()
    try:
        con.execute(
            "INSERT INTO approvals(id,action,payload_json,reason,status) VALUES(?,?,?,?, 'pending')",
            (approval_id, req.action, payload_json, req.reason),
        )
        con.commit()
    finally:
        con.close()
    _audit(
        "approval.requested",
        {
            "approval_id": approval_id,
            "action": req.action,
            "payload_sha256": hashlib.sha256(payload_json.encode()).hexdigest(),
        },
    )
    return {"id": approval_id, "status": "pending", "message": "No action has run yet."}


@app.post("/api/approvals/{approval_id}/decision")
def decide(approval_id: str, decision: str):
    if decision not in {"approve", "reject"}:
        raise HTTPException(422, "Decision must be approve or reject.")
    con = _db()
    try:
        row = con.execute(
            "SELECT status,action FROM approvals WHERE id=?", (approval_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Approval not found.")
        if row["status"] != "pending":
            raise HTTPException(409, "Approval already decided.")
        status = "approved" if decision == "approve" else "rejected"
        con.execute(
            "UPDATE approvals SET status=?,decided_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, approval_id),
        )
        con.commit()
    finally:
        con.close()
    _audit(
        "approval.decision",
        {"approval_id": approval_id, "decision": decision, "action": row["action"]},
    )
    return {"id": approval_id, "status": status}


@app.post("/api/workspace/write")
def write_file(req: FileWriteRequest):
    target = _safe_path(req.relative_path)
    content = req.content.encode("utf-8")
    content_hash = hashlib.sha256(content).hexdigest()
    approved = False
    if req.approval_id:
        con = _db()
        try:
            row = con.execute(
                "SELECT action,payload_json,status FROM approvals WHERE id=?",
                (req.approval_id,),
            ).fetchone()
            if row and row["status"] == "approved" and row["action"] == "workspace_write":
                try:
                    payload = json.loads(row["payload_json"])
                except (json.JSONDecodeError, TypeError):
                    payload = {}
                matches = (
                    payload.get("relative_path") == req.relative_path
                    and payload.get("content_sha256") == content_hash
                )
                if matches:
                    # Conditional update claims the approval once, even under concurrent requests.
                    claimed = con.execute(
                        "UPDATE approvals SET status='consuming' WHERE id=? AND status='approved'",
                        (req.approval_id,),
                    )
                    con.commit()
                    approved = claimed.rowcount == 1
        finally:
            con.close()
    policy = evaluate_tool("workspace_write", approved)
    if not policy.allowed:
        _audit("workspace.write.blocked", {"path": req.relative_path, "reason": policy.reason})
        raise HTTPException(403, policy.reason)

    snapshot_id = str(uuid.uuid4())
    existed = target.is_file()
    snapshot_dir = settings.workspace / ".nova-snapshots"
    backup_path = None
    if existed:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        backup = snapshot_dir / f"{snapshot_id}.bak"
        backup.write_bytes(target.read_bytes())
        backup_path = str(backup.relative_to(settings.workspace))
    con = _db()
    try:
        con.execute(
            "INSERT INTO snapshots(id,relative_path,existed,backup_path) VALUES(?,?,?,?)",
            (snapshot_id, req.relative_path, int(existed), backup_path),
        )
        con.commit()
    finally:
        con.close()
    try:
        _atomic_write(target, content)
    except OSError as exc:
        if req.approval_id and approved:
            con = _db()
            try:
                con.execute("UPDATE approvals SET status='failed' WHERE id=? AND status='consuming'", (req.approval_id,))
                con.commit()
            finally:
                con.close()
        _audit("workspace.write.failure", {"snapshot_id": snapshot_id, "error": type(exc).__name__})
        raise HTTPException(500, "Atomic workspace write failed; snapshot retained.") from exc
    if req.approval_id and approved:
        con = _db()
        try:
            con.execute("UPDATE approvals SET status='consumed' WHERE id=? AND status='consuming'", (req.approval_id,))
            con.commit()
        finally:
            con.close()
    _audit(
        "workspace.write",
        {
            "path": req.relative_path,
            "content_sha256": content_hash,
            "snapshot_id": snapshot_id,
            "approval_id": req.approval_id,
        },
    )
    return {
        "written": True,
        "path": req.relative_path,
        "snapshot_id": snapshot_id,
        "snapshot_created": True,
        "previous_file_existed": existed,
    }


@app.get("/api/workspace/snapshots")
def list_snapshots():
    con = _db()
    try:
        rows = con.execute(
            """SELECT id,relative_path,existed,created_at,rolled_back_at
            FROM snapshots ORDER BY created_at DESC LIMIT 100"""
        ).fetchall()
    finally:
        con.close()
    return [dict(row) for row in rows]


@app.post("/api/workspace/rollback")
def rollback(req: RollbackRequest):
    # A rollback is destructive: require an approved, snapshot-specific, single-use approval.
    con = _db()
    try:
        snapshot = con.execute(
            "SELECT * FROM snapshots WHERE id=?", (req.snapshot_id,)
        ).fetchone()
        if snapshot is None:
            raise HTTPException(404, "Snapshot not found.")
        if snapshot["rolled_back_at"] is not None:
            raise HTTPException(409, "This snapshot has already been rolled back.")
        approval = con.execute(
            "SELECT action,payload_json,status FROM approvals WHERE id=?",
            (req.approval_id,),
        ).fetchone()
        if not approval or approval["status"] != "approved" or approval["action"] != "rollback_snapshot":
            raise HTTPException(403, "A pending or missing rollback approval cannot authorize this action.")
        try:
            payload = json.loads(approval["payload_json"])
        except (json.JSONDecodeError, TypeError):
            payload = {}
        if payload.get("snapshot_id") != req.snapshot_id:
            raise HTTPException(403, "Rollback approval does not match this snapshot.")
        claimed = con.execute(
            "UPDATE approvals SET status='consuming' WHERE id=? AND status='approved'",
            (req.approval_id,),
        )
        if claimed.rowcount != 1:
            con.rollback()
            raise HTTPException(403, "Rollback approval has already been consumed.")
        relative_path = snapshot["relative_path"]
        target = _safe_path(relative_path)
        if snapshot["existed"]:
            if not snapshot["backup_path"]:
                raise HTTPException(500, "Snapshot metadata is incomplete.")
            backup = (settings.workspace / snapshot["backup_path"]).resolve()
            snapshot_root = (settings.workspace / ".nova-snapshots").resolve()
            if snapshot_root not in backup.parents or not backup.is_file():
                raise HTTPException(500, "Snapshot backup is missing or outside snapshot storage.")
            _atomic_write(target, backup.read_bytes())
        else:
            if target.exists():
                target.unlink()
        con.execute(
            "UPDATE snapshots SET rolled_back_at=CURRENT_TIMESTAMP WHERE id=?",
            (req.snapshot_id,),
        )
        con.execute(
            "UPDATE approvals SET status='consumed' WHERE id=? AND status='consuming'",
            (req.approval_id,),
        )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    _audit(
        "workspace.rollback",
        {"snapshot_id": req.snapshot_id, "path": relative_path, "approval_id": req.approval_id,
         "restored_previous_state": True},
    )
    return {"rolled_back": True, "snapshot_id": req.snapshot_id, "path": relative_path}


@app.get("/api/audit/verify")
def audit_status():
    valid, count = verify_audit(settings.audit_path)
    return {"valid": valid, "events_verified": count}


@app.get("/api/settings")
def get_settings():
    return {
        "mode": "offline",
        "llm_runtime": "LiteRT-LM only",
        "litert_base_url": settings.litert_base_url,
        "model_id": active_model_id(),
        "require_approval_for_writes": settings.require_approval_for_writes,
        "network_policy": "loopback-only",
        "tool_policy": "default-deny",
        "rollback_enabled": True,
        "huggingface_enabled": True,
        "huggingface_cache_dir": str(settings.huggingface_cache_dir),
        "huggingface_max_download_bytes": settings.huggingface_max_download_bytes,
        "huggingface_token_configured": bool(settings.huggingface_token or os.environ.get("NOVA_HUGGINGFACE_TOKEN", "").strip()),
    }

