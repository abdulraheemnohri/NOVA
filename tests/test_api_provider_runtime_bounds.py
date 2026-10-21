"""Regression tests for bounded API-provider request/response handling."""
from contextlib import contextmanager
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient

from nova.config import settings
from nova.main import app


class _BoundedProviderHandler(BaseHTTPRequestHandler):
    hits = 0
    response_size = 2048

    def do_GET(self):
        type(self).hits += 1
        payload = json.dumps({"value": "x" * type(self).response_size}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


@contextmanager
def _provider_server():
    _BoundedProviderHandler.hits = 0
    _BoundedProviderHandler.response_size = 2048
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BoundedProviderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _configure_test_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    settings.workspace.mkdir(parents=True, exist_ok=True)


def _create_provider(client, base_url, *, enabled=True, max_response_bytes=1024):
    response = client.post("/api/integrations/apis", json={
        "name": "Bounded test provider",
        "enabled": enabled,
        "config": {
            "base_url": base_url,
            "auth_type": "none",
            "allowed_paths": ["/v1/health"],
            "timeout_seconds": 3,
            "max_response_bytes": max_response_bytes,
        },
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_api_provider_rejects_response_over_configured_limit(monkeypatch, tmp_path):
    _configure_test_storage(monkeypatch, tmp_path)
    with _provider_server() as base_url, TestClient(app, client=("127.0.0.1", 50001)) as client:
        provider = _create_provider(client, base_url, max_response_bytes=1024)
        response = client.post(f"/api/integrations/apis/{provider['id']}/request", json={
            "path": "/v1/health",
            "method": "GET",
        })

    assert response.status_code == 502
    assert "size limit" in response.json()["detail"].lower()
    assert _BoundedProviderHandler.hits == 1


def test_api_provider_rejects_oversized_request_before_network_call(monkeypatch, tmp_path):
    _configure_test_storage(monkeypatch, tmp_path)
    with _provider_server() as base_url, TestClient(app, client=("127.0.0.1", 50002)) as client:
        provider = _create_provider(client, base_url)
        response = client.post(f"/api/integrations/apis/{provider['id']}/request", json={
            "path": "/v1/health",
            "method": "POST",
            "payload": {"value": "x" * 70000},
        })

    assert response.status_code == 413
    assert _BoundedProviderHandler.hits == 0


def test_disabled_api_provider_never_makes_network_call(monkeypatch, tmp_path):
    _configure_test_storage(monkeypatch, tmp_path)
    with _provider_server() as base_url, TestClient(app, client=("127.0.0.1", 50003)) as client:
        provider = _create_provider(client, base_url, enabled=False)
        response = client.post(f"/api/integrations/apis/{provider['id']}/request", json={
            "path": "/v1/health",
            "method": "GET",
        })

    assert response.status_code == 409
    assert _BoundedProviderHandler.hits == 0
