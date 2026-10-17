from contextlib import contextmanager
from fastapi.testclient import TestClient
from nova.main import app


@contextmanager
def _client(tmp_path, monkeypatch):
    from nova.config import settings
    from nova.audit import append_audit
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    token_path = tmp_path / "api.token"
    token_path.write_text("system-monitor-test-token")
    monkeypatch.setattr(settings, "api_token_file", token_path)
    append_audit(settings.audit_path, "test.start", {})
    with TestClient(app) as client:
        yield client, {"Authorization": "Bearer system-monitor-test-token"}


def test_system_metrics_endpoint_reports_resource_categories(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.get("/api/system", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert {"processor", "ram", "swap", "storage", "battery", "gpu", "npu", "tpu"} <= body.keys()
        assert body["processor"]["logical_cores"] >= 1
        assert 0 <= body["processor"]["utilization_percent"] <= 100
        assert body["ram"]["total_bytes"] > 0
        assert isinstance(body["storage"], list)
        assert "Read-only telemetry" in body["notes"][0]


def test_system_metrics_endpoint_requires_local_api_token(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _):
        response = client.get("/api/system")
        assert response.status_code == 401
