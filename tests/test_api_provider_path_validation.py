"""Regression tests for API provider allowlist path normalization."""
import pytest
from fastapi.testclient import TestClient

from nova.config import settings
from nova.main import app


def _configure_test_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    settings.workspace.mkdir(parents=True, exist_ok=True)


@pytest.mark.parametrize("path", [
    "/%2e%2e/admin",
    "/%252e%252e/admin",
    "/safe%2f..%2fadmin",
    "/safe%5c..%5cadmin",
    "/v1/health\nX-Injected: true",
    "/v1/%3fadmin",
    "/v1/./admin",
])
def test_api_provider_rejects_paths_that_normalize_unsafely(monkeypatch, tmp_path, path):
    _configure_test_storage(monkeypatch, tmp_path)
    with TestClient(app, client=("127.0.0.1", 50003)) as client:
        response = client.post("/api/integrations/apis", json={
            "name": "Unsafe path test",
            "enabled": False,
            "config": {
                "base_url": "https://api.example.com",
                "auth_type": "none",
                "allowed_paths": [path],
                "timeout_seconds": 3,
                "max_response_bytes": 1024,
            },
        })
    assert response.status_code == 422, response.text


def test_api_provider_accepts_simple_explicit_allowlist_path(monkeypatch, tmp_path):
    _configure_test_storage(monkeypatch, tmp_path)
    with TestClient(app, client=("127.0.0.1", 50004)) as client:
        response = client.post("/api/integrations/apis", json={
            "name": "Safe path test",
            "enabled": False,
            "config": {
                "base_url": "https://api.example.com",
                "auth_type": "none",
                "allowed_paths": ["/v1/health", "/v1/items/123"],
                "timeout_seconds": 3,
                "max_response_bytes": 1024,
            },
        })
    assert response.status_code == 201, response.text
