import json
import sys
from contextlib import contextmanager

from fastapi.testclient import TestClient

from nova.config import settings
from nova.main import app

_FAKE_MCP = r"""
import json, sys
for line in sys.stdin:
    try:
        msg = json.loads(line)
    except Exception:
        continue
    if "id" not in msg:
        continue
    method = msg.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [
            {"name": "read_info", "description": "Read-only fixture", "annotations": {"readOnlyHint": True}},
            {"name": "write_info", "description": "Mutating fixture", "annotations": {"readOnlyHint": False}}
        ]}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "called:" + msg["params"]["name"]}]}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "Method not found"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
"""


@contextmanager
def _client():
    with TestClient(app, client=("127.0.0.1", 50001)) as client:
        yield client


def _temp(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    settings.workspace.mkdir(parents=True, exist_ok=True)


def test_stdio_mcp_connect_discover_call_and_disconnect(monkeypatch, tmp_path):
    _temp(monkeypatch, tmp_path)
    with _client() as client:
        created = client.post("/api/integrations/mcp", json={
            "name": "Fake test MCP",
            "enabled": True,
            "config": {"transport": "stdio", "command": sys.executable, "args": ["-u", "-c", _FAKE_MCP]},
        })
        assert created.status_code == 201, created.text
        integration_id = created.json()["id"]

        connected = client.post(f"/api/integrations/mcp/{integration_id}/connect")
        assert connected.status_code == 200, connected.text
        assert connected.json()["connected"] is True
        assert connected.json()["tool_count"] == 2

        listed = client.get(f"/api/integrations/mcp/{integration_id}/tools")
        assert listed.status_code == 200
        assert {item["name"] for item in listed.json()["items"]} == {"read_info", "write_info"}

        read = client.post(f"/api/integrations/mcp/{integration_id}/tools/read_info/call", json={"arguments": {}})
        assert read.status_code == 200, read.text
        assert "called:read_info" in json.dumps(read.json())

        blocked = client.post(f"/api/integrations/mcp/{integration_id}/tools/write_info/call", json={"arguments": {}})
        assert blocked.status_code == 428

        allowed = client.post(
            f"/api/integrations/mcp/{integration_id}/tools/write_info/call",
            json={"arguments": {}, "confirm_side_effects": True},
        )
        assert allowed.status_code == 200, allowed.text

        disconnected = client.post(f"/api/integrations/mcp/{integration_id}/disconnect")
        assert disconnected.status_code == 200
        assert disconnected.json()["connected"] is False


def test_runtime_refuses_disabled_server(monkeypatch, tmp_path):
    _temp(monkeypatch, tmp_path)
    with _client() as client:
        created = client.post("/api/integrations/mcp", json={
            "name": "Disabled MCP",
            "enabled": False,
            "config": {"transport": "stdio", "command": sys.executable, "args": ["-u", "-c", _FAKE_MCP]},
        })
        assert created.status_code == 201
        response = client.post(f"/api/integrations/mcp/{created.json()['id']}/connect")
        assert response.status_code == 409
