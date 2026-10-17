"""Read-only runtime and host diagnostics for NOVA."""
from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from nova.audit import verify_audit
from nova.config import settings
from nova.litert import LiteRTError, health
from nova.model_manager import active_model_id

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


def _model_ids(payload: Any) -> list[str]:
    """Extract model IDs from common OpenAI-compatible /models response shapes."""
    if not isinstance(payload, dict):
        return []
    candidates = payload.get("data")
    if not isinstance(candidates, list):
        candidates = payload.get("models")
    if not isinstance(candidates, list):
        return []
    result: list[str] = []
    for item in candidates:
        if isinstance(item, dict):
            model_id = item.get("id") or item.get("name")
            if isinstance(model_id, str) and model_id.strip():
                result.append(model_id.strip())
    return sorted(set(result))


@router.get("")
def runtime_diagnostics() -> dict[str, Any]:
    """Report observable status only; never launches commands or changes settings."""
    configured_model = active_model_id()
    try:
        runtime = health()
    except LiteRTError as exc:
        runtime = {
            "reachable": False,
            "base_url": settings.litert_base_url,
            "message": str(exc),
        }

    model_ids = _model_ids(runtime.get("models_response"))
    reachable = runtime.get("reachable") is True
    model_known = configured_model in model_ids if model_ids else None
    workspace = settings.workspace
    try:
        usage = shutil.disk_usage(workspace if workspace.exists() else workspace.parent)
        disk = {
            "total_bytes": usage.total,
            "free_bytes": usage.free,
            "used_percent": round((usage.used / usage.total) * 100, 1) if usage.total else None,
        }
    except OSError:
        disk = {"available": False}

    db_parent = settings.database_path.expanduser().parent
    audit_valid, audit_events = verify_audit(settings.audit_path)
    cli_path = shutil.which("litert-lm")

    checks = [
        {"id": "litert_endpoint", "status": "pass" if reachable else "fail",
         "detail": "LiteRT-LM model endpoint responds." if reachable else runtime.get("message", "Endpoint unavailable.")},
        {"id": "configured_model", "status": ("pass" if model_known else "fail") if model_known is not None else "unknown",
         "detail": (f"Configured model '{configured_model}' is listed by the runtime." if model_known
                    else f"Configured model '{configured_model}' is not listed by the runtime."
                    if model_known is False else "Runtime model IDs could not be confirmed.")},
        {"id": "audit_chain", "status": "pass" if audit_valid else "fail",
         "detail": f"{audit_events} audit events verified." if audit_valid else "Audit chain is invalid or unavailable."},
        {"id": "workspace", "status": "pass" if workspace.exists() and workspace.is_dir() else "warn",
         "detail": "Workspace directory exists." if workspace.exists() and workspace.is_dir()
                   else "Workspace directory will be created on application startup."},
        {"id": "database_parent", "status": "pass" if db_parent.exists() else "warn",
         "detail": "Database parent directory exists." if db_parent.exists()
                   else "Database parent directory does not exist yet."},
    ]
    return {
        "read_only": True,
        "runtime": {
            "name": "LiteRT-LM",
            "endpoint": runtime.get("base_url", settings.litert_base_url),
            "reachable": reachable,
            "message": runtime.get("message"),
            "cli_found": bool(cli_path),
            "cli_path": cli_path,
            "version": None,
            "version_note": "Version is not executed or guessed; inspect the installed package using its release-specific instructions.",
            "configured_model_id": configured_model,
            "model_ids": model_ids,
            "configured_model_listed": model_known,
        },
        "host": {
            "platform": platform.platform(),
            "python_version": sys.version.split()[0],
            "workspace": str(workspace),
            "database_path": str(settings.database_path),
            "disk": disk,
        },
        "audit": {"valid": audit_valid, "events_verified": audit_events},
        "checks": checks,
        "limitations": [
            "Diagnostics are read-only and do not execute shell commands.",
            "A listed model ID does not prove artifact integrity, inference quality, or accelerator support.",
            "Runtime version and hardware acceleration are not inferred when the installed release does not expose verified metadata.",
        ],
    }
