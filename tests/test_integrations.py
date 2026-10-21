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
