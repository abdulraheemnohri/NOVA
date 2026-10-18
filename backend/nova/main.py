from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import hmac
import sqlite3
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from nova.audit import append_audit, verify_audit
from nova.config import settings
from nova.knowledge import SearchRequest, initialize_knowledge, router as knowledge_router, search_knowledge
from nova.litert import LiteRTError, chat, health
from nova.model_manager import active_model_id, router as model_router
from nova.huggingface import router as huggingface_router
from nova.policy import evaluate_tool
from nova.tasks import router as tasks_router
from nova.diagnostics import router as diagnostics_router
from nova.runtimes import router as runtimes_router
from nova.scheduler import router as scheduler_router, start_worker, stop_worker, initialize_scheduler_config
from nova.system_monitor import router as system_router
from nova.settings_preferences import get_preferences, get_feature_settings, router as settings_preferences_router
from nova.security import PersistentRateLimiter
from nova.identity import router as identity_router, compose_prompt
from nova.agent_tools import router as agent_tools_router
from nova.self_improvement import router as self_improvement_router
from nova.autonomy import router as autonomy_router
from nova.workflow_engine import (
    recover_interrupted_runs as recover_interrupted_workflow_runs,
    router as workflow_engine_router,
)
from nova.updates import router as updates_router, start_worker as start_update_worker, stop_worker as stop_update_worker
from nova.whatsapp import router as whatsapp_router

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Initialize persistent services once per process and stop workers on shutdown."""
    application.state.rate_limiter = PersistentRateLimiter(lambda: settings.database_path)
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
    # A process may stop after a side effect but before recording completion.
    # Quarantine such approvals instead of making them eligible for replay.
    _recover_interrupted_approvals()

    # Interrupted work is marked for operator review; it is never replayed.
    from nova.autonomy import recover_interrupted_runs
    from nova.self_improvement import recover_interrupted_skill_runs
    recover_interrupted_runs()
    recover_interrupted_skill_runs()
    recover_interrupted_workflow_runs()
    initialize_knowledge()
    initialize_scheduler_config()

    try:
        start_worker()
        start_update_worker()
        yield
    finally:
        stop_worker()
        stop_update_worker()


app = FastAPI(
    title="NOVA — Neural Offline Verified Agent",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.rate_limiter = PersistentRateLimiter(lambda: settings.database_path)


@app.middleware("http")
async def require_local_api_token(request: Request, call_next):
    # Health is intentionally public for local process supervision; all other API routes
    # require the generated, file-backed bearer token.
    if request.url.path == "/api/health" or (request.url.path == "/api/whatsapp/webhook" and request.method in {"GET", "POST"}) or not request.url.path.startswith("/api/"):
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


@app.middleware("http")
async def apply_api_security_controls(request: Request, call_next):
    # Use the direct peer address only; never trust caller-supplied forwarding headers.
    client_key = request.client.host if request.client else "unknown"
    limiter: PersistentRateLimiter = request.app.state.rate_limiter
    is_api = request.url.path.startswith("/api/")
    if is_api and (limiter.auth_blocked(client_key) or not limiter.allow(client_key)):
        response = JSONResponse(status_code=429, content={"detail": "API rate limit exceeded; retry shortly."})
    else:
        response = await call_next(request)
        if is_api and response.status_code == 401:
            limiter.record_auth_failure(client_key)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if is_api:
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(knowledge_router)
app.include_router(model_router)
app.include_router(huggingface_router)
app.include_router(tasks_router)
app.include_router(diagnostics_router)
app.include_router(runtimes_router)
app.include_router(scheduler_router)
app.include_router(system_router)
app.include_router(settings_preferences_router)
app.include_router(identity_router)
app.include_router(agent_tools_router)
app.include_router(self_improvement_router)
app.include_router(autonomy_router)
app.include_router(workflow_engine_router)
app.include_router(updates_router)
app.include_router(whatsapp_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
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



def _recover_interrupted_approvals() -> int:
    """Quarantine approvals left consuming after a crash; never replay side effects."""
    con = _db()
    try:
        rows = con.execute(
            "SELECT id,action FROM approvals WHERE status='consuming' ORDER BY created_at"
        ).fetchall()
        if not rows:
            return 0
        ids = [row["id"] for row in rows]
        con.executemany(
            "UPDATE approvals SET status='interrupted' WHERE id=? AND status='consuming'",
            [(approval_id,) for approval_id in ids],
        )
        con.commit()
    finally:
        con.close()
    _audit(
        "approval.recovery.interrupted",
        {
            "count": len(rows),
            "approval_ids": ids,
            "actions": sorted({row["action"] for row in rows}),
            "replay_performed": False,
            "operator_review_required": True,
        },
    )
    return len(rows)


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



def _ensure_snapshot_directory() -> Path:
    """Create/validate the internal snapshot directory without following symlinks."""
    root = settings.workspace.resolve()
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        snapshot_dir = root / ".nova-snapshots"
        if snapshot_dir.is_symlink():
            raise OSError("The internal snapshot store must not be a symbolic link")
        snapshot_dir.mkdir(mode=0o700, parents=False, exist_ok=True)
        if snapshot_dir.is_symlink() or not snapshot_dir.is_dir():
            raise OSError("The internal snapshot store is not a real directory")
        return snapshot_dir

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(root, directory_flags)
    try:
        try:
            os.mkdir(".nova-snapshots", mode=0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        snapshot_fd = os.open(".nova-snapshots", directory_flags, dir_fd=root_fd)
        try:
            if not stat.S_ISDIR(os.fstat(snapshot_fd).st_mode):
                raise OSError("The internal snapshot store is not a directory")
            os.fsync(root_fd)
        finally:
            os.close(snapshot_fd)
    finally:
        os.close(root_fd)
    return root / ".nova-snapshots"


def _read_relative_file(relative_path: str, *, allow_snapshot: bool = False) -> bytes:
    """Read a workspace or internal snapshot file without following symlinks on POSIX."""
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise OSError("Invalid workspace-relative read path")
    is_snapshot = relative.parts[0] == ".nova-snapshots"
    if is_snapshot and not allow_snapshot:
        raise OSError("Snapshot storage is reserved")
    if allow_snapshot and not is_snapshot:
        raise OSError("Snapshot backup path must stay in snapshot storage")

    root = settings.workspace.resolve()
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        target = _safe_path(relative_path) if not is_snapshot else (root / relative)
        if is_snapshot and (target.parent.resolve() != (root / ".nova-snapshots").resolve()):
            raise OSError("Snapshot path escapes internal storage")
        return target.read_bytes()

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(root, flags)
    opened_fds = []
    parent_fd = root_fd
    try:
        for part in relative.parts[:-1]:
            next_fd = os.open(part, flags, dir_fd=parent_fd)
            opened_fds.append(next_fd)
            parent_fd = next_fd
        file_fd = os.open(relative.parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise OSError("Workspace read target is not a regular file")
            chunks = []
            while True:
                chunk = os.read(file_fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(file_fd)
    finally:
        for fd in reversed(opened_fds):
            os.close(fd)
        os.close(root_fd)




def _unlink_relative_file(relative_path: str) -> bool:
    """Unlink a workspace-relative file without following swapped parent symlinks.

    Returns False when the target or one of its parent directories is absent.
    POSIX keeps each parent directory pinned by file descriptor until unlink
    completes, so replacing a checked directory with a symlink cannot redirect
    deletion outside the workspace.
    """
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise OSError("Invalid workspace-relative unlink path")
    if relative.parts[0] == ".nova-snapshots":
        raise OSError("Snapshot storage is reserved")

    root = settings.workspace.resolve()
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        target = _safe_path(relative_path)
        try:
            target.unlink()
            return True
        except FileNotFoundError:
            return False

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(root, directory_flags)
    opened_fds = []
    parent_fd = root_fd
    try:
        for part in relative.parts[:-1]:
            try:
                next_fd = os.open(part, directory_flags, dir_fd=parent_fd)
            except FileNotFoundError:
                return False
            opened_fds.append(next_fd)
            parent_fd = next_fd
        try:
            os.unlink(relative.parts[-1], dir_fd=parent_fd)
        except FileNotFoundError:
            return False
        os.fsync(parent_fd)
        return True
    finally:
        for fd in reversed(opened_fds):
            os.close(fd)
        os.close(root_fd)


def _atomic_write(target: Path, content: bytes):
    """Atomically replace a workspace file without following swapped path components.

    POSIX uses directory descriptors and O_NOFOLLOW for each component, so a
    symlink substituted after _safe_path validation cannot redirect the write.
    Other platforms retain the portable path-based fallback.
    """
    root = settings.workspace.resolve()
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise OSError("Workspace write target is outside the configured root") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise OSError("Invalid workspace-relative write target")

    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "supports_dir_fd") or os.open not in os.supports_dir_fd:
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
        return

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(root, directory_flags)
    parent_fd = root_fd
    opened_fds = []
    temp_name = None
    try:
        for part in relative.parts[:-1]:
            try:
                next_fd = os.open(part, directory_flags, dir_fd=parent_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=parent_fd)
                except FileExistsError:
                    pass
                next_fd = os.open(part, directory_flags, dir_fd=parent_fd)
            opened_fds.append(next_fd)
            parent_fd = next_fd

        leaf = relative.parts[-1]
        temp_name = f".nova-write-{secrets.token_hex(16)}"
        file_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        try:
            view = memoryview(content)
            while view:
                written = os.write(file_fd, view)
                if written <= 0:
                    raise OSError("Short write while saving workspace file")
                view = view[written:]
            os.fsync(file_fd)
        finally:
            os.close(file_fd)
        os.replace(temp_name, leaf, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        temp_name = None
        os.fsync(parent_fd)
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        for fd in reversed(opened_fds):
            os.close(fd)
        os.close(root_fd)


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
    # Retrieval is local and lexical today; returned source metadata is grounded in
    # the local index. Document text is untrusted evidence, never tool authority.
    features = get_feature_settings()\n    retrieval = search_knowledge(SearchRequest(query=req.message, limit=4)) if features["local_retrieval_enabled"] else {"results": [], "method": "disabled"}
    retrieved = retrieval.get("results", [])
    sources = [
        {
            "document_id": item["document_id"],
            "chunk_id": item["chunk_id"],
            "source": item["source"],
            "chunk_index": item["chunk_index"],
            "score": item["score"],
        }
        for item in retrieved
    ]
    excerpts = "\n\n".join(
        f"[Source {index + 1}: {item['source']} | document_id={item['document_id']} | chunk={item['chunk_index']}]\n{item['text']}"
        for index, item in enumerate(retrieved)
    ) if retrieved else ""
    prompt = compose_prompt(req.message, excerpts)
    _audit("chat.request", {
        "message_sha256": hashlib.sha256(req.message.encode()).hexdigest(),
        "retrieved_source_count": len(sources),
        "source_document_ids": [item["document_id"] for item in sources],
    })
    try:
        model_id = active_model_id()
        preferences = get_preferences()
        answer = chat(prompt, req.max_tokens, model_id=model_id, temperature=preferences["chat_temperature"])
    except LiteRTError as exc:
        _audit("chat.failure", {"error": str(exc)})
        raise HTTPException(503, str(exc)) from exc
    _audit("chat.response", {
        "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
        "retrieved_source_count": len(sources),
    })
    return {
        "answer": answer,
        "model": model_id,
        "runtime": "LiteRT-LM",
        "sources": sources,
        "retrieval_method": retrieval.get("method", "local_keyword"),
    }


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
        # Claim the pending decision atomically. A concurrent request may have
        # changed the status after the SELECT above, so never update by id alone.
        claimed = con.execute(
            "UPDATE approvals SET status=?,decided_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND status='pending'",
            (status, approval_id),
        )
        if claimed.rowcount != 1:
            con.rollback()
            raise HTTPException(409, "Approval already decided.")
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
    try:
        snapshot_dir = _ensure_snapshot_directory()
    except OSError as exc:
        raise HTTPException(403, "The internal snapshot store must be a real, non-symlink directory.") from exc
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
    backup_path = None
    if existed:
        try:
            # The snapshot directory is opened/validated without following links;
            # the backup itself uses the same descriptor-relative atomic writer
            # as ordinary workspace files.
            snapshot_dir = _ensure_snapshot_directory()
            backup_path = f".nova-snapshots/{snapshot_id}.bak"
            _atomic_write(settings.workspace.resolve() / backup_path, _read_relative_file(req.relative_path))
        except OSError as exc:
            if req.approval_id and approved:
                con = _db()
                try:
                    con.execute("UPDATE approvals SET status='failed' WHERE id=? AND status='consuming'", (req.approval_id,))
                    con.commit()
                finally:
                    con.close()
            _audit("workspace.snapshot.failure", {"path": req.relative_path, "error": type(exc).__name__})
            raise HTTPException(500, "Unable to create a safe workspace snapshot; no write was attempted.") from exc
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
            snapshot_store = settings.workspace / ".nova-snapshots"
            if snapshot_store.is_symlink():
                raise HTTPException(500, "The internal snapshot store must not be a symbolic link.")
            workspace_root = settings.workspace.resolve()
            snapshot_root = snapshot_store.resolve()
            if snapshot_root.parent != workspace_root or snapshot_root.name != ".nova-snapshots":
                raise HTTPException(500, "The internal snapshot store is outside its expected location.")
            backup = (settings.workspace / snapshot["backup_path"]).resolve()
            if snapshot_root not in backup.parents or not backup.is_file():
                raise HTTPException(500, "Snapshot backup is missing or outside snapshot storage.")
            _atomic_write(target, _read_relative_file(snapshot["backup_path"], allow_snapshot=True))
        else:
            # Deletion is descriptor-relative on POSIX; a swapped parent symlink
            # cannot redirect rollback outside the workspace.
            _unlink_relative_file(relative_path)
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

