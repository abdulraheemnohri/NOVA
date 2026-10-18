"""Validated, persistent operator preferences; security policy remains environment-controlled."""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from typing import Any
from fastapi import APIRouter
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
