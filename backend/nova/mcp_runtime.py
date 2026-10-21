"""Explicitly managed MCP stdio runtime (no shell, bounded JSON-RPC, opt-in tool calls)."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from nova.audit import append_audit
from nova.config import settings
from nova.integrations import _list
from nova import mcp_remote_runtime as remote_mcp

router = APIRouter(prefix="/api/integrations/mcp", tags=["mcp-runtime"])
MAX_LINE_BYTES = 1_000_000
MAX_TOOLS = 250
MAX_TIMEOUT = 30.0
MAX_ARGUMENT_BYTES = 64_000


@dataclass
class Session:
    integration_id: str
    process: asyncio.subprocess.Process
    reader_task: asyncio.Task
    pending: dict[int, asyncio.Future] = field(default_factory=dict)
    tools: list[dict[str, Any]] = field(default_factory=list)
    next_id: int = 1
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stderr_task: asyncio.Task | None = None
    last_error: str | None = None


_sessions: dict[str, Session] = {}
_sessions_lock = asyncio.Lock()


def _integration(integration_id: str) -> dict[str, Any]:
    for item in _list("mcp"):
        if item["id"] == integration_id:
            return item
    raise HTTPException(404, "MCP integration not found.")


def _public(session: Session) -> dict[str, Any]:
    return {
        "id": session.integration_id,
        "connected": session.process.returncode is None,
        "pid": session.process.pid,
        "tool_count": len(session.tools),
        "tools": [
            {
                "name": t.get("name", ""),
                "description": str(t.get("description", ""))[:1000],
                "read_only": bool((t.get("annotations") or {}).get("readOnlyHint", False)),
            }
            for t in session.tools
        ],
        "last_error": session.last_error,
    }


async def _read_stderr(session: Session) -> None:
    stream = session.process.stderr
    if stream is None:
        return
    while True:
        line = await stream.readline()
        if not line:
            return
        # Deliberately discard server stderr instead of retaining potentially sensitive output.


async def _reader(session: Session) -> None:
    stream = session.process.stdout
    if stream is None:
        return
    try:
        while True:
            line = await stream.readline()
            if not line:
                break
            if len(line) > MAX_LINE_BYTES:
                session.last_error = "MCP server emitted a message exceeding the size limit."
                break
            try:
                message = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(message, dict) or not isinstance(message.get("id"), int):
                continue
            future = session.pending.pop(message["id"], None)
            if future is not None and not future.done():
                if "error" in message:
                    future.set_exception(RuntimeError("MCP request failed: " + str(message["error"])[:500]))
                else:
                    future.set_result(message.get("result", {}))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        session.last_error = type(exc).__name__
    finally:
        for future in list(session.pending.values()):
            if not future.done():
                future.set_exception(RuntimeError("MCP process disconnected."))
        session.pending.clear()


async def _request(session: Session, method: str, params: dict[str, Any] | None = None) -> Any:
    if session.process.returncode is not None or session.process.stdin is None:
        raise RuntimeError("MCP process is not running.")
    async with session.lock:
        request_id = session.next_id
        session.next_id += 1
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        session.pending[request_id] = future
        message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
        try:
            encoded = (json.dumps(message, separators=(",", ":")) + "\n").encode()
            if len(encoded) > MAX_ARGUMENT_BYTES:
                raise HTTPException(413, "MCP request exceeds the size limit.")
            session.process.stdin.write(encoded)
            await asyncio.wait_for(session.process.stdin.drain(), timeout=5)
            return await asyncio.wait_for(future, timeout=MAX_TIMEOUT)
        except asyncio.TimeoutError as exc:
            session.pending.pop(request_id, None)
            raise RuntimeError("MCP request timed out.") from exc
        except Exception:
            session.pending.pop(request_id, None)
            raise


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    arguments: dict[str, Any] = Field(default_factory=dict)
    confirm_side_effects: bool = False


@router.post("/{integration_id}/connect")
async def connect_mcp(integration_id: str):
    item = _integration(integration_id)
    if not item["enabled"]:
        raise HTTPException(409, "Enable this MCP configuration before connecting.")
    config = item["config"]
    if config.get("transport", "stdio") == "streamable_http":
        return await remote_mcp.connect_remote(integration_id)
    if config.get("transport", "stdio") != "stdio":
        raise HTTPException(422, "Unsupported MCP transport.")
    command = config.get("command")
    args = config.get("args", [])
    if not isinstance(command, str) or not command.strip() or not isinstance(args, list):
        raise HTTPException(422, "Invalid stdio command configuration.")
    if not all(isinstance(arg, str) and len(arg) <= 500 for arg in args) or len(args) > 40:
        raise HTTPException(422, "Invalid stdio arguments.")
    executable = shutil.which(command)
    if executable is None:
        raise HTTPException(422, f"Executable '{command}' was not found on the NOVA server PATH.")
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), "LANG": os.environ.get("LANG", "C.UTF-8")}
    refs = config.get("env_refs", {})
    if isinstance(refs, dict):
        for child_name, parent_name in refs.items():
            if isinstance(child_name, str) and isinstance(parent_name, str) and parent_name in os.environ:
                env[child_name] = os.environ[parent_name]
    async with _sessions_lock:
        old = _sessions.get(integration_id)
        if old and old.process.returncode is None:
            return _public(old)
        try:
            process = await asyncio.create_subprocess_exec(
                executable, *args,
                cwd=str(settings.workspace.resolve()),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=MAX_LINE_BYTES + 1,
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(422, f"Could not start MCP server ({type(exc).__name__}).") from exc
        session = Session(integration_id, process, asyncio.create_task(asyncio.sleep(0)))
        session.reader_task = asyncio.create_task(_reader(session))
        session.stderr_task = asyncio.create_task(_read_stderr(session))
        _sessions[integration_id] = session
    try:
        await _request(session, "initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "NOVA", "version": "0.1.0"},
        })
        process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        await process.stdin.drain()
        result = await _request(session, "tools/list", {})
        tools = result.get("tools", []) if isinstance(result, dict) else []
        if not isinstance(tools, list) or len(tools) > MAX_TOOLS:
            raise RuntimeError("MCP server returned an invalid or oversized tools list.")
        session.tools = [t for t in tools if isinstance(t, dict) and isinstance(t.get("name"), str)]
        append_audit(settings.audit_path, "mcp.runtime.connected", {"integration_id": integration_id, "pid": process.pid, "tool_count": len(session.tools)})
        return _public(session)
    except Exception as exc:
        await _stop(session)
        async with _sessions_lock:
            _sessions.pop(integration_id, None)
        append_audit(settings.audit_path, "mcp.runtime.connect_failed", {"integration_id": integration_id, "error_type": type(exc).__name__})
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(502, f"MCP server failed to initialize: {str(exc)[:250]}") from exc


async def _stop(session: Session) -> None:
    if session.process.returncode is None:
        session.process.terminate()
        try:
            await asyncio.wait_for(session.process.wait(), timeout=3)
        except asyncio.TimeoutError:
            session.process.kill()
            await session.process.wait()
    for task in (session.reader_task, session.stderr_task):
        if task and not task.done():
            task.cancel()
    await asyncio.gather(*(t for t in (session.reader_task, session.stderr_task) if t), return_exceptions=True)


@router.get("/{integration_id}/status")
async def mcp_status(integration_id: str):
    item = _integration(integration_id)
    if item["config"].get("transport", "stdio") == "streamable_http":
        remote = remote_mcp.remote_status(integration_id)
        return {"id": integration_id, "connected": bool(remote), **(remote or {})}
    session = _sessions.get(integration_id)
    return {"id": integration_id, "connected": bool(session and session.process.returncode is None), **(_public(session) if session else {})}


@router.get("/{integration_id}/tools")
async def mcp_tools(integration_id: str):
    item = _integration(integration_id)
    if item["config"].get("transport", "stdio") == "streamable_http":
        remote_tools = remote_mcp.remote_tools(integration_id)
        if remote_tools is None:
            raise HTTPException(409, "Remote MCP server is not connected.")
        return {"items": remote_tools}
    session = _sessions.get(integration_id)
    if not session or session.process.returncode is not None:
        raise HTTPException(409, "MCP server is not connected.")
    return {"items": _public(session)["tools"]}


@router.post("/{integration_id}/tools/{tool_name}/call")
async def call_mcp_tool(integration_id: str, tool_name: str, request: ToolCall):
    item = _integration(integration_id)
    if item["config"].get("transport", "stdio") == "streamable_http":
        remote_tools = remote_mcp.remote_tools(integration_id)
        if remote_tools is None:
            raise HTTPException(409, "Remote MCP server is not connected.")
        tool = next((t for t in remote_tools if t.get("name") == tool_name), None)
        if tool is None:
            raise HTTPException(404, "Tool not found in the connected server's discovered tool list.")
        read_only = bool(tool.get("read_only", (tool.get("annotations") or {}).get("readOnlyHint", False)))
        if not read_only and not request.confirm_side_effects:
            raise HTTPException(428, "Tool may have side effects. Retry only after explicit operator confirmation with confirm_side_effects=true.")
        try:
            result = await remote_mcp.call_remote(integration_id, tool_name, request.arguments)
        except HTTPException:
            raise
        except Exception as exc:
            append_audit(settings.audit_path, "mcp.remote.tool_failed", {"integration_id": integration_id, "tool": tool_name, "error_type": type(exc).__name__})
            raise HTTPException(502, "Remote MCP tool call failed.") from exc
        return {"integration_id": integration_id, "tool": tool_name, "result": result}
    session = _sessions.get(integration_id)
    if not session or session.process.returncode is not None:
        raise HTTPException(409, "MCP server is not connected.")
    tool = next((t for t in session.tools if t.get("name") == tool_name), None)
    if tool is None:
        raise HTTPException(404, "Tool not found in the connected server's discovered tool list.")
    read_only = bool((tool.get("annotations") or {}).get("readOnlyHint", False))
    if not read_only and not request.confirm_side_effects:
        raise HTTPException(428, "Tool may have side effects. Retry only after explicit operator confirmation with confirm_side_effects=true.")
    args_bytes = json.dumps(request.arguments, ensure_ascii=False).encode()
    if len(args_bytes) > MAX_ARGUMENT_BYTES:
        raise HTTPException(413, "Tool arguments exceed the size limit.")
    try:
        result = await _request(session, "tools/call", {"name": tool_name, "arguments": request.arguments})
    except Exception as exc:
        append_audit(settings.audit_path, "mcp.runtime.tool_failed", {"integration_id": integration_id, "tool": tool_name, "error_type": type(exc).__name__})
        raise HTTPException(502, f"MCP tool call failed: {str(exc)[:250]}") from exc
    append_audit(settings.audit_path, "mcp.runtime.tool_called", {"integration_id": integration_id, "tool": tool_name, "read_only": read_only})
    return {"integration_id": integration_id, "tool": tool_name, "result": result}


@router.post("/{integration_id}/disconnect")
async def disconnect_mcp(integration_id: str):
    item = _integration(integration_id)
    if item["config"].get("transport", "stdio") == "streamable_http":
        await remote_mcp.disconnect_remote(integration_id)
        return {"id": integration_id, "connected": False}
    async with _sessions_lock:
        session = _sessions.pop(integration_id, None)
    if session:
        await _stop(session)
        append_audit(settings.audit_path, "mcp.runtime.disconnected", {"integration_id": integration_id})
    return {"id": integration_id, "connected": False}


async def shutdown_mcp_sessions() -> None:
    async with _sessions_lock:
        sessions = list(_sessions.values())
        _sessions.clear()
    await asyncio.gather(*(_stop(session) for session in sessions), return_exceptions=True)
    await remote_mcp.shutdown_remote_sessions()
