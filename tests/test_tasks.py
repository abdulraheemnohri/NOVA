from fastapi.testclient import TestClient
from nova.main import app

def _setup(tmp_path, monkeypatch):
    from nova.config import settings
    from nova.audit import append_audit
    monkeypatch.setattr(settings, "database_path", tmp_path / "tasks.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    token_path = tmp_path / "api.token"
    token_path.write_text("test-token")
    monkeypatch.setattr(settings, "api_token_file", token_path)
    append_audit(settings.audit_path, "test.start", {})
    return TestClient(app), {"Authorization": "Bearer test-token"}

def test_task_queue_lifecycle(tmp_path, monkeypatch):
    client, headers = _setup(tmp_path, monkeypatch)
    created = client.post("/api/tasks", headers=headers, json={
        "title": "Review model compatibility", "priority": "high",
        "plan": ["Inspect model metadata", "Run a local smoke test"],
    })
    assert created.status_code == 201
    task = created.json()
    assert task["status"] == "queued"
    assert task["plan"] == ["Inspect model metadata", "Run a local smoke test"]
    assert client.post(f"/api/tasks/{task['id']}/status", headers=headers, json={"status": "planned"}).status_code == 200
    started = client.post(f"/api/tasks/{task['id']}/status", headers=headers, json={"status": "in_progress"})
    assert started.status_code == 200 and started.json()["attempts"] == 1
    assert client.delete(f"/api/tasks/{task['id']}", headers=headers).status_code == 409
    assert client.post(f"/api/tasks/{task['id']}/status", headers=headers, json={
        "status": "completed", "result": "Smoke test passed"
    }).status_code == 200
    assert client.get("/api/tasks", headers=headers).json()[0]["status"] == "completed"

def test_task_rejects_invalid_transition_and_timezone(tmp_path, monkeypatch):
    client, headers = _setup(tmp_path, monkeypatch)
    task_id = client.post("/api/tasks", headers=headers, json={"title": "A"}).json()["id"]
    invalid = client.post(f"/api/tasks/{task_id}/status", headers=headers, json={"status": "completed"})
    assert invalid.status_code == 409
    due = client.post("/api/tasks", headers=headers, json={"title": "B", "due_at": "2026-10-17T12:00:00"})
    assert due.status_code == 422
