"""Validated, persistent operator preferences; security policy remains environment-controlled."""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from nova.audit import append_audit
from nova.config import settings

router = APIRouter(prefix="/api/settings", tags=["settings"])
DEFAULT_PREFERENCES = {"chat_max_tokens": 512, "chat_temperature": 0.2, "auto_refresh_seconds": 0, "confirm_model_selection": True}

class PreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chat_max_tokens: int = Field(default=512, ge=64, le=4096)
    chat_temperature: float = Field(default=0.2, ge=0.0, le=1.5)
    auto_refresh_seconds: int = Field(default=0, ge=0, le=300)
    confirm_model_selection: bool = True

def _connect() -> sqlite3.Connection:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(settings.database_path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS nova_settings (
        key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    return con

def get_preferences() -> dict[str, Any]:
    con = _connect()
    try:
        rows = {r["key"]: r["value"] for r in con.execute(
            """SELECT key,value FROM nova_settings WHERE key IN
            ('ui_chat_max_tokens','ui_chat_temperature','ui_auto_refresh_seconds','ui_confirm_model_selection')"""
        ).fetchall()}
    finally:
        con.close()
    result = dict(DEFAULT_PREFERENCES)
    try:
        if "ui_chat_max_tokens" in rows: result["chat_max_tokens"] = int(rows["ui_chat_max_tokens"])
        if "ui_chat_temperature" in rows: result["chat_temperature"] = float(rows["ui_chat_temperature"])
        if "ui_auto_refresh_seconds" in rows: result["auto_refresh_seconds"] = int(rows["ui_auto_refresh_seconds"])
        if "ui_confirm_model_selection" in rows: result["confirm_model_selection"] = rows["ui_confirm_model_selection"] == "true"
    except (ValueError, TypeError):
        return dict(DEFAULT_PREFERENCES)
    return result

@router.get("/preferences")
def read_preferences() -> dict[str, Any]:
    return get_preferences()

@router.put("/preferences")
def update_preferences(req: PreferencesUpdate) -> dict[str, Any]:
    values = {
        "ui_chat_max_tokens": str(req.chat_max_tokens),
        "ui_chat_temperature": str(req.chat_temperature),
        "ui_auto_refresh_seconds": str(req.auto_refresh_seconds),
        "ui_confirm_model_selection": "true" if req.confirm_model_selection else "false",
    }
    now = datetime.now(timezone.utc).isoformat()
    con = _connect()
    try:
        con.executemany(
            """INSERT INTO nova_settings(key,value,updated_at) VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
            [(k, v, now) for k, v in values.items()],
        )
        con.commit()
    finally:
        con.close()
    append_audit(settings.audit_path, "settings.preferences.updated", {
        "chat_max_tokens": req.chat_max_tokens,
        "chat_temperature": req.chat_temperature,
        "auto_refresh_seconds": req.auto_refresh_seconds,
        "confirm_model_selection": req.confirm_model_selection,
    })
    return get_preferences()


# Runtime feature switches are operational preferences, not permission grants.
# Defaults preserve current behavior; sensitive policy remains environment-controlled.
DEFAULT_FEATURES = {
    "local_retrieval_enabled": True,
    "model_hub_enabled": True,
    "model_downloads_enabled": True,
    "whisper_enabled": True,
    "piper_enabled": True,
    "ocr_enabled": True,
    "onnx_runtime_enabled": True,
    "max_model_download_bytes": 20_000_000_000,
}

class FeatureSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local_retrieval_enabled: bool = True
    model_hub_enabled: bool = True
    model_downloads_enabled: bool = True
    whisper_enabled: bool = True
    piper_enabled: bool = True
    ocr_enabled: bool = True
    onnx_runtime_enabled: bool = True
    max_model_download_bytes: int = Field(default=20_000_000_000, ge=1_000_000, le=20_000_000_000)

def get_feature_settings() -> dict[str, Any]:
    con = _connect()
    keys = {key: "feature_" + key for key in DEFAULT_FEATURES}
    try:
        rows = {r["key"]: r["value"] for r in con.execute(
            "SELECT key,value FROM nova_settings WHERE key LIKE 'feature_%'"
        ).fetchall()}
    finally:
        con.close()
    result = dict(DEFAULT_FEATURES)
    for name, key in keys.items():
        if key not in rows:
            continue
        try:
            if name == "max_model_download_bytes":
                result[name] = min(int(rows[key]), int(settings.huggingface_max_download_bytes))
            else:
                result[name] = rows[key] == "true"
        except (ValueError, TypeError):
            continue
    # Environment policy always sets the hard upper bound; UI cannot raise it.
    result["max_model_download_bytes"] = min(
        int(result["max_model_download_bytes"]), int(settings.huggingface_max_download_bytes)
    )
    return result

@router.get("/features")
def read_feature_settings() -> dict[str, Any]:
    return get_feature_settings()

@router.put("/features")
def update_feature_settings(req: FeatureSettingsUpdate) -> dict[str, Any]:
    values = req.model_dump()
    now = datetime.now(timezone.utc).isoformat()
    hard_limit = int(settings.huggingface_max_download_bytes)
    if req.max_model_download_bytes > hard_limit:
        raise HTTPException(422, "Model download limit cannot exceed NOVA_HUGGINGFACE_MAX_DOWNLOAD_BYTES.")
    con = _connect()
    try:
        con.executemany(
            """INSERT INTO nova_settings(key,value,updated_at) VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
            [("feature_" + key, str(value).lower(), now) for key, value in values.items()],
        )
        con.commit()
    finally:
        con.close()
    append_audit(settings.audit_path, "settings.features.updated", {
        key: value for key, value in values.items()
    })
    return get_feature_settings()


# These are operator-controlled capability switches for model-initiated actions.
# Project-wide settings and security policy are deliberately not exposed as AI capabilities.
DEFAULT_AI_CAPABILITIES = {
    "ai_tool_calls_enabled": True,
    "ai_skill_use_enabled": True,
    "ai_skill_generation_enabled": True,
    "ai_tool_proposal_enabled": True,
    "ai_runtime_management_enabled": True,
    "ai_runtime_configuration_enabled": True,
    "ai_project_settings_access": False,
}

class AICapabilitiesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ai_tool_calls_enabled: bool = True
    ai_skill_use_enabled: bool = True
    ai_skill_generation_enabled: bool = True
    ai_tool_proposal_enabled: bool = True
    ai_runtime_management_enabled: bool = True
    ai_runtime_configuration_enabled: bool = True

def get_ai_capabilities() -> dict[str, bool]:
    con = _connect()
    try:
        rows = {row["key"]: row["value"] for row in con.execute(
            "SELECT key,value FROM nova_settings WHERE key LIKE 'ai_capability_%'"
        ).fetchall()}
    finally:
        con.close()
    result = dict(DEFAULT_AI_CAPABILITIES)
    for name in tuple(result):
        if name == "ai_project_settings_access":
            result[name] = False
            continue
        value = rows.get("ai_capability_" + name)
        if value is not None:
            result[name] = value == "true"
    return result

@router.get("/ai-capabilities")
def read_ai_capabilities() -> dict[str, bool]:
    return get_ai_capabilities()

@router.put("/ai-capabilities")
def update_ai_capabilities(req: AICapabilitiesUpdate) -> dict[str, bool]:
    values = req.model_dump()
    now = datetime.now(timezone.utc).isoformat()
    con = _connect()
    try:
        con.executemany(
            """INSERT INTO nova_settings(key,value,updated_at) VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
            [("ai_capability_" + key, str(value).lower(), now) for key, value in values.items()],
        )
        con.commit()
    finally:
        con.close()
    append_audit(settings.audit_path, "settings.ai_capabilities.updated", values)
    return get_ai_capabilities()

@router.get("/live-status")
def read_live_status() -> dict[str, Any]:
    """Live overview snapshot. Reports detected state; it does not start runtimes."""
    from nova.audit import verify_audit
    from nova.runtimes import runtime_inventory
    from nova.agent_tools import catalog as tool_catalog
    from nova.self_improvement import list_skills, list_tool_proposals
    from nova.litert import health as litert_health
    from nova.model_manager import active_model_id
    active_model_for_status = active_model_id

    valid, event_count = verify_audit(settings.audit_path)
    endpoint = urlsplit(settings.litert_base_url)
    safe_endpoint = urlunsplit((endpoint.scheme, endpoint.netloc.rsplit("@", 1)[-1], endpoint.path, "", ""))
    try:
        inventory = runtime_inventory()
    except Exception as exc:
        inventory = {"primary_chat_runtime": "LiteRT-LM", "automatic_fallback": False,
                     "runtimes": [], "notes": ["Runtime inventory failed: " + type(exc).__name__]}
    capabilities = get_ai_capabilities()
    features = get_feature_settings()
    tools = tool_catalog().get("tools", [])
    skills_result = list_skills()
    proposals_result = list_tool_proposals()
    runtime_items = inventory.get("runtimes", [])
    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "environment": settings.env,
            "workspace_path": str(settings.workspace),
            "database_path": str(settings.database_path),
            "audit_log_path": str(settings.audit_path),
            "api_token_file": str(settings.api_token_file),
            "chat_runtime": "LiteRT-LM only",
            "LiteRT_endpoint": safe_endpoint,
            "configured_model": active_model_for_status(),
            "chat_timeout_seconds": settings.litert_chat_timeout_seconds,
            "write_approval_required": settings.require_approval_for_writes,
            "scheduler_enabled": settings.scheduler_enabled,
            "scheduler_interval_seconds": settings.scheduler_interval_seconds,
            "semantic_retrieval_environment_default": settings.semantic_retrieval_enabled,
            "onnx_runtime_environment_default": settings.onnxruntime_enabled,
            "whisper_cli_path": settings.whisper_cli_path or "auto-detect",
            "whisper_model_path": str(settings.whisper_model_path),
            "whisper_timeout_seconds": settings.whisper_timeout_seconds,
            "ffmpeg_cli_path": settings.ffmpeg_cli_path or "auto-detect",
            "piper_cli_path": settings.piper_cli_path or "auto-detect",
            "piper_model_path": str(settings.piper_model_path),
            "tesseract_cli_path": settings.tesseract_cli_path or "auto-detect",
            "pdf_ocr_enabled": settings.pdf_ocr_enabled,
            "pdf_ocr_max_pages": settings.pdf_ocr_max_pages,
            "pdf_renderer_cli_path": settings.pdf_renderer_cli_path or "not configured",
            "huggingface_cache_dir": str(settings.huggingface_cache_dir),
            "huggingface_max_download_bytes": get_feature_settings()["max_model_download_bytes"],
            "huggingface_token_configured": bool(settings.huggingface_token or __import__("os").environ.get("NOVA_HUGGINGFACE_TOKEN", "").strip()),
            "secrets": "Values redacted; configure secrets in the local environment or protected token files.",
        },
        "runtime": {
            "primary": inventory.get("primary_chat_runtime", "LiteRT-LM"),
            "chat": litert_health(),
            "automatic_fallback": bool(inventory.get("automatic_fallback", False)),
            "items": runtime_items,
            "ready_count": sum(1 for item in runtime_items if item.get("status") == "ready"),
            "detected_count": sum(1 for item in runtime_items if item.get("detected")),
            "notes": inventory.get("notes", []),
        },
        "security": {
            "api_authentication": "bearer-token",
            "audit_chain_valid": valid,
            "audit_events": event_count,
            "unknown_tools": "denied",
            "project_settings_control": "human-only",
            "write_authority": "approval-gated",
            "network_policy": "loopback-only",
        },
        "ai": {
            "capabilities": capabilities,
            "registered_tools": len(tools),
            "skills": len(skills_result.get("skills", [])),
            "active_skills": sum(1 for item in skills_result.get("skills", []) if item.get("status") == "active"),
            "tool_proposals": len(proposals_result.get("tools", [])),
            "enabled_features": [key for key, value in features.items() if isinstance(value, bool) and value],
        },
    }
