"""Bounded MCP Streamable HTTP transport.

Remote transport is explicit and separate from local stdio subprocesses. Requests are
JSON-RPC over HTTPS (HTTP is accepted only for loopback endpoints), redirects are
rejected, responses are bounded, and credentials are read from environment variables.
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException

from nova.audit import append_audit
from nova.config import settings
from nova.integrations import _list

MAX_RESPONSE_BYTES = 1_000_000
MAX_REQUEST_BYTES = 64_000
REQUEST_TIMEOUT = 15.0
MAX_TOOLS = 250


@dataclass
class RemoteSession:
    integration_id: str
    endpoint: str
    headers: dict[str, str]
    session_id: str | None = None
    protocol_version: str = "2025-03-26"
    tools: list[dict[str, Any]] = field(default_factory=list)
    last_error: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_sessions: dict[str, RemoteSession] = {}


def _integration(integration_id: str) -> dict[str, Any]:
    for item in _list("mcp"):
        if item["id"] == integration_id:
            return item
    raise HTTPException(404, "MCP integration not found.")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "MCP redirects are disabled", headers, fp)


def _sync_request(session: RemoteSession, method: str, params: dict[str, Any] | None, request_id: int | None) -> Any:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        payload["id"] = request_id
    if params is not None:
        payload["params"] = params
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_REQUEST_BYTES:
        raise ValueError("MCP request exceeds the size limit")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "NOVA-MCP/0.1",
        **session.headers,
    }
    if session.session_id:
        headers["Mcp-Session-Id"] = session.session_id
    if session.protocol_version:
        headers["MCP-Protocol-Version"] = session.protocol_version
    req = urllib.request.Request(session.endpoint, data=body, headers=headers, method="POST")
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("MCP response exceeds the size limit")
            new_session_id = response.headers.get("Mcp-Session-Id")
            if new_session_id:
                session.session_id = new_session_id
            content_type = response.headers.get("Content-Type", "").lower()
            if response.status == 202 and request_id is None:
                return {}
            if not raw:
                return {}
            text = raw.decode("utf-8", errors="strict")
            if "text/event-stream" in content_type:
                data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
                for data in reversed(data_lines):
                    if data and data != "[DONE]":
                        parsed = json.loads(data)
                        if request_id is None or parsed.get("id") == request_id:
                            message = parsed
                            break
                else:
                    return {}
            else:
                message = json.loads(text)
            if not isinstance(message, dict):
                raise ValueError("MCP server returned a non-object JSON-RPC response")
            if "error" in message:
                raise RuntimeError("MCP request failed: " + str(message["error"])[:400])
            return message.get("result", {})
    except urllib.error.HTTPError as exc:
        # Do not include response bodies, URLs, or headers that may contain secrets.
        raise RuntimeError(f"MCP HTTP request failed with status {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"MCP transport failed ({type(exc).__name__})") from exc


async def _request(session: RemoteSession, method: str, params: dict[str, Any] | None = None, *, notification: bool = False) -> Any:
    async with session.lock:
        request_id = None if notification else 1
        return await asyncio.wait_for(
            asyncio.to_thread(_sync_request, session, method, params, request_id),
            timeout=REQUEST_TIMEOUT + 2,
        )


def _public(session: RemoteSession) -> dict[str, Any]:
    return {
        "id": session.integration_id,
        "connected": True,
        "transport": "streamable_http",
        "tool_count": len(session.tools),
        "tools": [
            {
                "name": tool.get("name", ""),
                "description": str(tool.get("description", ""))[:1000],
                "read_only": bool((tool.get("annotations") or {}).get("readOnlyHint", False)),
            }
            for tool in session.tools
        ],
        "last_error": session.last_error,
    }


async def connect_remote(integration_id: str) -> dict[str, Any]:
    item = _integration(integration_id)
    if not item["enabled"]:
        raise HTTPException(409, "Enable this MCP configuration before connecting.")
    config = item["config"]
    if config.get("transport") != "streamable_http":
        raise HTTPException(422, "This integration is not configured for Streamable HTTP.")
    endpoint = config.get("endpoint", "")
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise HTTPException(422, "Invalid remote MCP endpoint.")
    headers: dict[str, str] = {}
    bearer_env = config.get("bearer_env")
    if bearer_env:
        secret = os.environ.get(bearer_env)
        if not secret:
            raise HTTPException(422, f"Required credential environment variable '{bearer_env}' is not set.")
        headers["Authorization"] = "Bearer " + secret
    existing = _sessions.get(integration_id)
    if existing:
        return _public(existing)
    session = RemoteSession(integration_id=integration_id, endpoint=endpoint, headers=headers)
    try:
        initialized = await _request(session, "initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "NOVA", "version": "0.1.0"},
        })
        if not isinstance(initialized, dict):
            raise RuntimeError("MCP initialize returned an invalid result")
        version = initialized.get("protocolVersion")
        if isinstance(version, str) and version:
            session.protocol_version = version
        await _request(session, "notifications/initialized", notification=True)
        result = await _request(session, "tools/list", {})
        tools = result.get("tools", []) if isinstance(result, dict) else []
        if not isinstance(tools, list) or len(tools) > MAX_TOOLS:
            raise RuntimeError("MCP server returned an invalid or oversized tools list")
        session.tools = [tool for tool in tools if isinstance(tool, dict) and isinstance(tool.get("name"), str)]
        _sessions[integration_id] = session
        append_audit(settings.audit_path, "mcp.remote.connected", {"integration_id": integration_id, "tool_count": len(session.tools)})
        return _public(session)
    except HTTPException:
        raise
    except Exception as exc:
        append_audit(settings.audit_path, "mcp.remote.connect_failed", {"integration_id": integration_id, "error_type": type(exc).__name__})
        raise HTTPException(502, f"Remote MCP server failed to initialize: {type(exc).__name__}.") from exc


def remote_status(integration_id: str) -> dict[str, Any] | None:
    session = _sessions.get(integration_id)
    return _public(session) if session else None


def remote_tools(integration_id: str) -> list[dict[str, Any]] | None:
    session = _sessions.get(integration_id)
    return _public(session)["tools"] if session else None


async def call_remote(integration_id: str, tool_name: str, arguments: dict[str, Any]) -> Any:
    session = _sessions.get(integration_id)
    if not session:
        raise HTTPException(409, "Remote MCP server is not connected.")
    tool = next((item for item in session.tools if item.get("name") == tool_name), None)
    if tool is None:
        raise HTTPException(404, "Tool not found in the connected server's discovered tool list.")
    if len(json.dumps(arguments, ensure_ascii=False).encode("utf-8")) > MAX_REQUEST_BYTES:
        raise HTTPException(413, "Tool arguments exceed the size limit.")
    try:
        result = await _request(session, "tools/call", {"name": tool_name, "arguments": arguments})
    except Exception as exc:
        append_audit(settings.audit_path, "mcp.remote.tool_failed", {"integration_id": integration_id, "tool": tool_name, "error_type": type(exc).__name__})
        raise HTTPException(502, f"Remote MCP tool call failed: {type(exc).__name__}.") from exc
    append_audit(settings.audit_path, "mcp.remote.tool_called", {"integration_id": integration_id, "tool": tool_name, "read_only": bool((tool.get("annotations") or {}).get("readOnlyHint", False))})
    return result


async def disconnect_remote(integration_id: str) -> bool:
    session = _sessions.pop(integration_id, None)
    if not session:
        return False
    if session.session_id:
        # Session deletion is best-effort; some MCP servers do not implement DELETE.
        def _delete() -> None:
            request = urllib.request.Request(
                session.endpoint,
                headers={**session.headers, "Mcp-Session-Id": session.session_id or ""},
                method="DELETE",
            )
            opener = urllib.request.build_opener(_NoRedirect())
            try:
                with opener.open(request, timeout=5):
                    pass
            except Exception:
                pass
        await asyncio.to_thread(_delete)
    append_audit(settings.audit_path, "mcp.remote.disconnected", {"integration_id": integration_id})
    return True


async def shutdown_remote_sessions() -> None:
    await asyncio.gather(*(disconnect_remote(key) for key in list(_sessions)), return_exceptions=True)
