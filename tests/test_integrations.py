from contextlib import contextmanager
from fastapi.testclient import TestClient
from nova.config import settings
from nova.main import app

@contextmanager
def _client():
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        yield client

def _temp(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    settings.workspace.mkdir(parents=True, exist_ok=True)

def test_mcp_config_crud_and_secret_reference_only(monkeypatch, tmp_path):
    _temp(monkeypatch, tmp_path)
    with _client() as client:
        created = client.post("/api/integrations/mcp", json={
            "name": "Local Git", "enabled": False,
            "config": {"transport": "stdio", "command": "uvx", "args": ["mcp-server-git", "/tmp/repo"],
                       "env_refs": {"TOKEN": "NOVA_TEST_TOKEN"}}
        })
        assert created.status_code == 201, created.text
        item = created.json()
        assert item["config"]["env_refs"]["TOKEN"] == "NOVA_TEST_TOKEN"
        changed = client.patch(f"/api/integrations/mcp/{item['id']}", json={"enabled": True})
        assert changed.status_code == 200
        assert changed.json()["enabled"] is True
        assert client.get("/api/integrations/mcp").json()["items"][0]["id"] == item["id"]
        assert client.delete(f"/api/integrations/mcp/{item['id']}").json()["deleted"] is True

def test_mcp_remote_http_requires_https(monkeypatch, tmp_path):
    _temp(monkeypatch, tmp_path)
    with _client() as client:
        response = client.post("/api/integrations/mcp", json={
            "name": "Insecure remote", "config": {"transport": "streamable_http", "endpoint": "http://example.com/mcp"}
        })
    assert response.status_code == 422

def test_api_config_rejects_secret_values(monkeypatch, tmp_path):
    _temp(monkeypatch, tmp_path)
    with _client() as client:
        response = client.post("/api/integrations/apis", json={
            "name": "Example API", "config": {"base_url": "https://api.example.com", "auth_type": "bearer_env", "api_key_env": "super-secret-token"}
        })
    assert response.status_code == 422

def test_catalog_labels_templates_as_not_connected():
    with _client() as client:
        response = client.get("/api/integrations/catalog")
    assert response.status_code == 200
    data = response.json()
    assert any(x["id"] == "filesystem" for x in data["mcp_servers"])
    assert any(x["id"] == "duckduckgo-search" for x in data["online_tools"])
    assert any("templates" in note for note in data["notes"])


import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import nova.main as main_module


class _ProviderHandler(BaseHTTPRequestHandler):
    hits = 0
    auth_seen = ""
    redirect = False

    def do_GET(self):
        type(self).hits += 1
        type(self).auth_seen = self.headers.get("Authorization", "")
        if type(self).redirect:
            self.send_response(302)
            self.send_header("Location", "/elsewhere")
            self.end_headers()
            return
        payload = json.dumps({"ok": True, "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


@contextmanager
def _provider_server():
    _ProviderHandler.hits = 0
    _ProviderHandler.auth_seen = ""
    _ProviderHandler.redirect = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _create_api_provider(client, base_url, **overrides):
    config = {
        "base_url": base_url,
        "auth_type": "bearer_env",
        "api_key_env": "NOVA_TEST_PROVIDER_TOKEN",
        "allowed_paths": ["/v1/health"],
        "timeout_seconds": 3,
        "max_response_bytes": 4096,
    }
    config.update(overrides)
    response = client.post("/api/integrations/apis", json={
        "name": "Test provider", "enabled": True, "config": config,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_api_provider_runtime_is_allowlisted_audited_and_redacts_secret(monkeypatch, tmp_path):
    _temp(monkeypatch, tmp_path)
    monkeypatch.setenv("NOVA_TEST_PROVIDER_TOKEN", "must-not-appear-in-audit")
    with _provider_server() as base_url, _client() as client:
        provider = _create_api_provider(client, base_url)
        response = client.post(f"/api/integrations/apis/{provider['id']}/request", json={
            "path": "/v1/health", "method": "GET",
        })
        assert response.status_code == 200, response.text
        assert response.json()["data"]["ok"] is True
        assert _ProviderHandler.auth_seen == "Bearer must-not-appear-in-audit"
        assert _ProviderHandler.hits == 1
        denied = client.post(f"/api/integrations/apis/{provider['id']}/request", json={
            "path": "/v1/not-allowed", "method": "GET",
        })
        assert denied.status_code == 403
    audit_text = (tmp_path / "audit.jsonl").read_text()
    assert "integration.api_request_succeeded" in audit_text
    assert "must-not-appear-in-audit" not in audit_text


def test_api_provider_runtime_rejects_redirects_and_private_mode_payload(monkeypatch, tmp_path):
    _temp(monkeypatch, tmp_path)
    monkeypatch.setenv("NOVA_TEST_PROVIDER_TOKEN", "secret")
    with _provider_server() as base_url, _client() as client:
        provider = _create_api_provider(client, base_url)
        _ProviderHandler.redirect = True
        redirected = client.post(f"/api/integrations/apis/{provider['id']}/request", json={
            "path": "/v1/health", "method": "GET",
        })
        assert redirected.status_code == 502
        # The provider runtime is a dedicated integration action, not a ChatRequest
        # capability; its schema rejects attempts to pass chat mode or extra routing.
        invalid = client.post(f"/api/integrations/apis/{provider['id']}/request", json={
            "path": "/v1/health", "method": "GET", "mode": "private",
        })
        assert invalid.status_code == 422
        assert _ProviderHandler.hits == 1


def test_private_chat_cannot_invoke_api_provider_action(monkeypatch, tmp_path):
    _temp(monkeypatch, tmp_path)
    monkeypatch.setattr(main_module, "active_model_id", lambda: "test-model")
    monkeypatch.setattr(main_module, "_model_enabled", lambda _model_id: True)
    monkeypatch.setattr(main_module, "get_feature_settings", lambda: {"local_retrieval_enabled": False})
    monkeypatch.setattr(main_module, "get_ai_capabilities", lambda: {
        "ai_tool_calls_enabled": False, "ai_skill_use_enabled": False,
        "ai_skill_generation_enabled": False, "ai_tool_proposal_enabled": False,
        "ai_runtime_configuration_enabled": False, "ai_runtime_management_enabled": False,
    })
    monkeypatch.setattr(main_module, "get_preferences", lambda: {"chat_temperature": 0.2})
    monkeypatch.setattr(main_module, "compose_prompt", lambda *args, **kwargs: "test prompt")
    monkeypatch.setattr(main_module, "chat", lambda *args, **kwargs: json.dumps({
        "nova_api_provider": {"id": "provider-id", "path": "/v1/health"},
    }))
    with _provider_server() as base_url, _client() as client:
        provider = _create_api_provider(client, base_url)
        response = client.post("/api/chat", json={"message": "call this provider", "mode": "private"})
        assert response.status_code == 200, response.text
        assert _ProviderHandler.hits == 0
        assert provider["id"] not in response.text
