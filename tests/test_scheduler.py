from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from nova.audit import append_audit
from nova.config import settings
from nova.main import app


@contextmanager
def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    monkeypatch.setattr(settings, "scheduler_enabled", False)
    monkeypatch.setattr(settings, "scheduler_interval_seconds", 15)
    token_path = tmp_path / "api.token"
    token_path.write_text("scheduler-test-token", encoding="utf-8")
    append_audit(settings.audit_path, "test.start", {})
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        yield client, {}


def test_run_once_moves_due_task_to_planned_without_execution(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, headers):
        due = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        created = client.post("/api/tasks", headers=headers, json={
            "title": "Due local review", "due_at": due, "plan": ["Inspect the report"]
        })
        assert created.status_code == 201, created.text
        task_id = created.json()["id"]

        response = client.post("/api/scheduler/run-once", headers=headers)
        assert response.status_code == 200, response.text
        assert task_id in response.json()["planned"]
        assert response.json()["claimed"] == 1
        task = next(row for row in client.get("/api/tasks", headers=headers).json() if row["id"] == task_id)
        assert task["status"] == "planned"
        assert "no command or tool was executed" in response.json()["message"]


def test_scheduler_leaves_future_tasks_queued_and_reports_disabled_worker(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, headers):
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        created = client.post("/api/tasks", headers=headers, json={"title": "Future", "due_at": future})
        assert created.status_code == 201
        response = client.post("/api/scheduler/run-once", headers=headers)
        assert response.status_code == 200
        assert response.json()["planned"] == []
        status = client.get("/api/scheduler/status", headers=headers)
        assert status.status_code == 200
        assert status.json()["enabled"] is False
        assert status.json()["due_tasks_waiting"] == 0


def test_scheduler_is_available_from_loopback(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.get("/api/scheduler/status")
        assert response.status_code == 200



def test_scheduler_config_is_validated_and_persisted(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.put("/api/scheduler/config", headers=headers, json={
            "enabled": False, "interval_seconds": 30
        })
        assert response.status_code == 200, response.text
        assert response.json()["enabled"] is False
        assert response.json()["interval_seconds"] == 30
        bad = client.put("/api/scheduler/config", headers=headers, json={
            "enabled": True, "interval_seconds": 1
        })
        assert bad.status_code == 422
        from nova.scheduler import initialize_scheduler_config
        monkeypatch.setattr(settings, "scheduler_enabled", True)
        monkeypatch.setattr(settings, "scheduler_interval_seconds", 10)
        initialize_scheduler_config()
        assert settings.scheduler_enabled is False
        assert settings.scheduler_interval_seconds == 30
