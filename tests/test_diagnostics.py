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
    token_path.write_text("diagnostics-test-token")
    monkeypatch.setattr(settings, "api_token_file", token_path)
    append_audit(settings.audit_path, "test.start", {})
    with TestClient(app) as client:
        yield client, {"Authorization": "Bearer diagnostics-test-token"}


def test_diagnostics_reports_runtime_and_model_status(tmp_path, monkeypatch):
    from nova.config import settings
    from nova import diagnostics

    monkeypatch.setattr(settings, "litert_model", "local-model")
    monkeypatch.setattr(diagnostics, "active_model_id", lambda: "local-model")
    monkeypatch.setattr(diagnostics, "health", lambda: {
        "reachable": True,
        "base_url": "http://127.0.0.1:9379/v1",
        "models_response": {"data": [{"id": "local-model"}, {"id": "other-model"}]},
    })
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.get("/api/diagnostics", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["read_only"] is True
        assert body["runtime"]["reachable"] is True
        assert body["runtime"]["configured_model_listed"] is True
        assert body["runtime"]["model_ids"] == ["local-model", "other-model"]
        assert body["audit"]["valid"] is True
        assert all(check["status"] in {"pass", "warn", "fail", "unknown"} for check in body["checks"])


def test_diagnostics_does_not_claim_unknown_model_compatibility(tmp_path, monkeypatch):
    from nova.config import settings
    from nova import diagnostics

    monkeypatch.setattr(settings, "litert_model", "missing-model")
    monkeypatch.setattr(diagnostics, "active_model_id", lambda: "missing-model")
    monkeypatch.setattr(diagnostics, "health", lambda: {
        "reachable": True,
        "base_url": "http://127.0.0.1:9379/v1",
        "models_response": {"data": [{"id": "available-model"}]},
    })
    with _client(tmp_path, monkeypatch) as (client, headers):
        body = client.get("/api/diagnostics", headers=headers).json()
        assert body["runtime"]["configured_model_listed"] is False
        check = next(item for item in body["checks"] if item["id"] == "configured_model")
        assert check["status"] == "fail"
        assert any("does not prove" in note for note in body["limitations"])


def test_diagnostics_requires_local_api_token(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _headers):
        response = client.get("/api/diagnostics")
        assert response.status_code == 401


def test_diagnostic_authority_is_allowlisted_and_exec_requires_confirmation(tmp_path, monkeypatch):
    from nova import diagnostics
    with _client(tmp_path, monkeypatch) as (client, headers):
        authority = client.get("/api/diagnostics/authority", headers=headers)
        assert authority.status_code == 200
        data = authority.json()
        assert data["arbitrary_shell_enabled"] is False
        assert any(item["id"] == "python-version" for item in data["commands"])
        missing_confirmation = client.post("/api/diagnostics/execute", headers=headers, json={
            "command_id": "python-version", "confirm_execution": False,
        })
        assert missing_confirmation.status_code == 400
        arbitrary = client.post("/api/diagnostics/execute", headers=headers, json={
            "command_id": "rm-rf", "confirm_execution": True,
        })
        assert arbitrary.status_code == 422
        result = client.post("/api/diagnostics/execute", headers=headers, json={
            "command_id": "python-version", "confirm_execution": True,
        })
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "succeeded"
        assert result.json()["shell_used"] is False
        assert "Python" in result.json()["output"] or "python" in result.json()["output"].lower()
