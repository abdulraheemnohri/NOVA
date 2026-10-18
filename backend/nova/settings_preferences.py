"""Validated, persistent operator preferences; security policy remains environment-controlled."""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from typing import Any
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
    "max_model_download_bytes": 2_000_000_000,
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
    max_model_download_bytes: int = Field(default=2_000_000_000, ge=1_000_000, le=2_000_000_000)

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
