import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient

from nova.config import settings
from nova.main import app


@contextmanager
def _client():
    with TestClient(app, client=("127.0.0.1", 50002)) as client:
        yield client


def _temp(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    settings.workspace.mkdir(parents=True, exist_ok=True)


class _MCPHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        method = payload.get("method")
        request_id = payload.get("id")
        if method == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "nova-test", "version": "1.0"},
            }
        elif method == "tools/list":
            result = {"tools": [
                {"name": "read_status", "description": "Read-only", "annotations": {"readOnlyHint": True}},
                {"name": "write_status", "description": "Side effect", "annotations": {"readOnlyHint": False}},
            ]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": "called:" + payload["params"]["name"]}]}
        else:
            self.send_response(400)
            self.end_headers()
            return
        body = json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", "test-session")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self):
        self.send_response(204)
        self.end_headers()


def test_remote_streamable_http_connect_discover_call_and_disconnect(monkeypatch, tmp_path):
    _temp(monkeypatch, tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MCPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = f"http://127.0.0.1:{server.server_port}/mcp"
        with _client() as client:
            created = client.post("/api/integrations/mcp", json={
                "name": "Remote local-test MCP",
                "enabled": True,
                "config": {"transport": "streamable_http", "endpoint": endpoint},
            })
            assert created.status_code == 201, created.text
            integration_id = created.json()["id"]

            connected = client.post(f"/api/integrations/mcp/{integration_id}/connect")
            assert connected.status_code == 200, connected.text
            assert connected.json()["connected"] is True
            assert connected.json()["transport"] == "streamable_http"
            assert connected.json()["tool_count"] == 2

            listed = client.get(f"/api/integrations/mcp/{integration_id}/tools")
            assert listed.status_code == 200
            assert {tool["name"] for tool in listed.json()["items"]} == {"read_status", "write_status"}

            read = client.post(f"/api/integrations/mcp/{integration_id}/tools/read_status/call", json={"arguments": {}})
            assert read.status_code == 200, read.text
            assert "called:read_status" in json.dumps(read.json())

            blocked = client.post(f"/api/integrations/mcp/{integration_id}/tools/write_status/call", json={"arguments": {}})
            assert blocked.status_code == 428

            allowed = client.post(
                f"/api/integrations/mcp/{integration_id}/tools/write_status/call",
                json={"arguments": {}, "confirm_side_effects": True},
            )
            assert allowed.status_code == 200, allowed.text

            status = client.get(f"/api/integrations/mcp/{integration_id}/status")
            assert status.status_code == 200
            assert status.json()["connected"] is True

            disconnected = client.post(f"/api/integrations/mcp/{integration_id}/disconnect")
            assert disconnected.status_code == 200
            assert disconnected.json()["connected"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_remote_mcp_bearer_secret_is_referenced_not_stored(monkeypatch, tmp_path):
    _temp(monkeypatch, tmp_path)
    with _client() as client:
        invalid = client.post("/api/integrations/mcp", json={
            "name": "Invalid secret config",
            "config": {
                "transport": "streamable_http",
                "endpoint": "https://mcp.example.test/mcp",
                "bearer_env": "do-not-store-this-secret",
            },
        })
    assert invalid.status_code == 422
