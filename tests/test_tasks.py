from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from nova.main import app

@contextmanager
def _client(tmp_path, monkeypatch):
    from nova.config import settings
    from nova.audit import append_audit
    monkeypatch.setattr(settings, "database_path", tmp_path / "tasks.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    token_path = tmp_path / "api.token"
    token_path.write_text("test-token")
    monkeypatch.setattr(settings, "api_token_file", token_path)
    append_audit(settings.audit_path, "test.start", {})
    with TestClient(app) as client:
        yield client, {"Authorization": "Bearer test-token"}

def test_task_queue_lifecycle(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, headers):
        created = client.post("/api/tasks", headers=headers, json={
            "title": "Review model compatibility", "priority": "high",
            "plan": ["Inspect model metadata", "Run a local smoke test"],
        })
        assert created.status_code == 201
        task = created.json()
        assert task["status"] == "queued"
        assert task["plan"] == ["Inspect model metadata", "Run a local smoke test"]
        planned = client.post(f"/api/tasks/{task['id']}/status", headers=headers, json={"status": "planned"})
        assert planned.status_code == 200
        started = client.post(f"/api/tasks/{task['id']}/status", headers=headers, json={"status": "in_progress"})
        assert started.status_code == 200 and started.json()["attempts"] == 1
        assert client.delete(f"/api/tasks/{task['id']}", headers=headers).status_code == 409
        finished = client.post(f"/api/tasks/{task['id']}/status", headers=headers, json={
            "status": "completed", "result": "Smoke test passed"
        })
        assert finished.status_code == 200
        assert client.get("/api/tasks", headers=headers).json()[0]["status"] == "completed"

def test_task_rejects_invalid_transition_and_timezone(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, headers):
        task_id = client.post("/api/tasks", headers=headers, json={"title": "A"}).json()["id"]
        invalid = client.post(f"/api/tasks/{task_id}/status", headers=headers, json={"status": "completed"})
        assert invalid.status_code == 409
        due = client.post("/api/tasks", headers=headers, json={"title": "B", "due_at": "2026-10-17T12:00:00"})
        assert due.status_code == 422


def test_task_retry_budget_is_enforced(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, headers):
        created = client.post("/api/tasks", headers=headers, json={
            "title": "Bounded retry task", "max_attempts": 2
        })
        assert created.status_code == 201
        task = created.json()
        assert task["attempts"] == 0
        assert task["max_attempts"] == 2

        def transition(status, expected=200):
            response = client.post(
                f"/api/tasks/{task['id']}/status", headers=headers,
                json={"status": status, "result": "test failure" if status == "failed" else None},
            )
            assert response.status_code == expected, response.text
            return response

        transition("planned")
        assert transition("in_progress").json()["attempts"] == 1
        transition("failed")
        transition("queued")
        transition("planned")
        assert transition("in_progress").json()["attempts"] == 2
        transition("failed")
        transition("queued", 409)
        transition("in_progress", 409)
        current = client.get("/api/tasks", headers=headers).json()[0]
        assert current["status"] == "failed"
        assert current["attempts"] == current["max_attempts"] == 2


def test_task_retry_budget_validation_and_legacy_migration(tmp_path, monkeypatch):
    import sqlite3
    from nova.config import settings

    with _client(tmp_path, monkeypatch) as (client, headers):
        invalid = client.post("/api/tasks", headers=headers, json={
            "title": "Invalid retry budget", "max_attempts": 11
        })
        assert invalid.status_code == 422

    legacy_path = tmp_path / "legacy.sqlite3"
    con = sqlite3.connect(legacy_path)
    con.execute("""CREATE TABLE tasks (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'queued', priority TEXT NOT NULL DEFAULT 'normal',
        due_at TEXT, plan_json TEXT NOT NULL DEFAULT '[]', result TEXT,
        attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    con.commit()
    con.close()
    monkeypatch.setattr(settings, "database_path", legacy_path)
    from nova.tasks import _connect
    migrated = _connect()
    try:
        columns = {row[1] for row in migrated.execute("PRAGMA table_info(tasks)")}
        assert migrated.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    finally:
        migrated.close()
    assert "max_attempts" in columns


def test_concurrent_task_start_counts_only_one_attempt(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, headers):
        created = client.post("/api/tasks", headers=headers, json={
            "title": "Concurrent start regression", "max_attempts": 2
        })
        assert created.status_code == 201
        task_id = created.json()["id"]
        planned = client.post(
            f"/api/tasks/{task_id}/status", headers=headers, json={"status": "planned"}
        )
        assert planned.status_code == 200

        def start_task(_):
            return client.post(
                f"/api/tasks/{task_id}/status",
                headers=headers,
                json={"status": "in_progress"},
            )

        # Two clients racing to start the same task should observe one real
        # transition and one idempotent response, never two attempt increments.
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(start_task, range(2)))

        assert all(response.status_code == 200 for response in responses)
        assert sum(bool(response.json().get("unchanged")) for response in responses) == 1
        stored = next(
            item for item in client.get("/api/tasks", headers=headers).json()
            if item["id"] == task_id
        )
        assert stored["status"] == "in_progress"
        assert stored["attempts"] == 1
