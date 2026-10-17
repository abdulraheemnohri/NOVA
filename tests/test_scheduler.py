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
    token_path = tmp_path / "api.token"
    token_path.write_text("scheduler-test-token", encoding="utf-8")
    monkeypatch.setattr(settings, "api_token_file", token_path)
    append_audit(settings.audit_path, "test.start", {})
    with TestClient(app) as client:
        yield client, {"Authorization": "Bearer scheduler-test-token"}


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


def test_scheduler_requires_api_token(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.get("/api/scheduler/status")
        assert response.status_code == 401
