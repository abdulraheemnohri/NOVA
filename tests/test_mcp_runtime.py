import json
import sys
from contextlib import contextmanager

from fastapi.testclient import TestClient

from nova.config import settings
from nova.main import app

_FAKE_MCP_PATH = str(__import__("pathlib").Path(__file__).parent / "fixtures" / "fake_mcp_server.py")


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
            "config": {"transport": "stdio", "command": sys.executable, "args": ["-u", _FAKE_MCP_PATH]},
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
            "config": {"transport": "stdio", "command": sys.executable, "args": ["-u", _FAKE_MCP_PATH]},
        })
        assert created.status_code == 201
        response = client.post(f"/api/integrations/mcp/{created.json()['id']}/connect")
        assert response.status_code == 409



def test_mcp_sandbox_off_preserves_direct_command(tmp_path):
    from nova.mcp_sandbox import build_mcp_command

    command = build_mcp_command("/usr/bin/python3", ["-u", "server.py"], tmp_path, "off")
    assert command == ["/usr/bin/python3", "-u", "server.py"]


def test_mcp_bwrap_mode_fails_closed_when_unavailable(tmp_path, monkeypatch):
    import pytest
    from nova import mcp_sandbox
    from nova.mcp_sandbox import SandboxUnavailableError, build_mcp_command

    monkeypatch.setattr(mcp_sandbox.shutil, "which", lambda _: None)
    with pytest.raises(SandboxUnavailableError, match="bubblewrap"):
        build_mcp_command("/usr/bin/python3", ["server.py"], tmp_path, "bwrap-readonly-root")


def test_mcp_bwrap_command_contains_readonly_root_and_writable_workspace(tmp_path, monkeypatch):
    from nova import mcp_sandbox
    from nova.mcp_sandbox import build_mcp_command

    monkeypatch.setattr(mcp_sandbox.sys, "platform", "linux")
    command = build_mcp_command(
        "/usr/bin/python3", ["server.py"], tmp_path, "bwrap-readonly-root",
        bwrap_path="/usr/bin/bwrap",
    )
    assert command[0] == "/usr/bin/bwrap"
    assert command[command.index("--ro-bind") + 1:command.index("--ro-bind") + 3] == ["/", "/"]
    assert command[command.index("--bind") + 1:command.index("--bind") + 3] == [str(tmp_path.resolve()), str(tmp_path.resolve())]
    assert command[-2:] == ["/usr/bin/python3", "server.py"]
