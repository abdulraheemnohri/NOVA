import hashlib

from fastapi.testclient import TestClient

from nova.config import settings
from nova.main import app


def test_health_is_litert_only():
    with TestClient(app) as client:
        data = client.get("/api/health").json()
    assert data["offline_mode"] is True
    assert data["llm_runtime"] == "LiteRT-LM only"


def test_unknown_approval_is_denied():
    with TestClient(app) as client:
        response = client.post(
            "/api/approvals",
            json={"action": "arbitrary_shell", "payload": {}, "reason": "test"},
        )
    assert response.status_code == 403


def _configure_temp_store(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    settings.workspace.mkdir(parents=True, exist_ok=True)


def _approve_write(client, relative_path: str, content: str) -> str:
    payload = {
        "relative_path": relative_path,
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
    }
    created = client.post(
        "/api/approvals",
        json={"action": "workspace_write", "payload": payload, "reason": "test approved write"},
    )
    assert created.status_code == 200, created.text
    approval_id = created.json()["id"]
    decision = client.post(f"/api/approvals/{approval_id}/decision?decision=approve")
    assert decision.status_code == 200, decision.text
    return approval_id




def _approve_rollback(client, snapshot_id: str) -> str:
    created = client.post(
        "/api/approvals",
        json={
            "action": "rollback_snapshot",
            "payload": {"snapshot_id": snapshot_id},
            "reason": "test approved rollback",
        },
    )
    assert created.status_code == 200, created.text
    approval_id = created.json()["id"]
    decision = client.post(f"/api/approvals/{approval_id}/decision?decision=approve")
    assert decision.status_code == 200, decision.text
    return approval_id


def test_write_snapshot_and_rollback_restores_previous_file(monkeypatch, tmp_path):
    _configure_temp_store(monkeypatch, tmp_path)
    original = settings.workspace / "report.txt"
    original.write_text("original", encoding="utf-8")
    with TestClient(app) as client:
        content = "updated report"
        approval_id = _approve_write(client, "report.txt", content)
        written = client.post(
            "/api/workspace/write",
            json={"relative_path": "report.txt", "content": content, "approval_id": approval_id},
        )
        assert written.status_code == 200, written.text
        snapshot_id = written.json()["snapshot_id"]
        assert original.read_text(encoding="utf-8") == content
        replay = client.post(
            "/api/workspace/write",
            json={"relative_path": "report.txt", "content": content, "approval_id": approval_id},
        )
        assert replay.status_code == 403, "an approved write token must be single-use"

        rollback_approval = _approve_rollback(client, snapshot_id)
        restored = client.post("/api/workspace/rollback", json={"snapshot_id": snapshot_id, "approval_id": rollback_approval})
        assert restored.status_code == 200, restored.text
        assert original.read_text(encoding="utf-8") == "original"
        second_approval = _approve_rollback(client, snapshot_id)
        assert client.post(
            "/api/workspace/rollback",
            json={"snapshot_id": snapshot_id, "approval_id": second_approval},
        ).status_code == 409


def test_rollback_removes_file_created_by_write(monkeypatch, tmp_path):
    _configure_temp_store(monkeypatch, tmp_path)
    with TestClient(app) as client:
        approval_id = _approve_write(client, "new.txt", "new content")
        written = client.post(
            "/api/workspace/write",
            json={"relative_path": "new.txt", "content": "new content", "approval_id": approval_id},
        )
        assert written.status_code == 200, written.text
        target = settings.workspace / "new.txt"
        assert target.exists()
        rollback_approval = _approve_rollback(client, written.json()["snapshot_id"])
        rolled_back = client.post(
            "/api/workspace/rollback",
            json={"snapshot_id": written.json()["snapshot_id"], "approval_id": rollback_approval},
        )
        assert rolled_back.status_code == 200, rolled_back.text
        assert not target.exists()


def test_workspace_write_rejects_path_traversal(monkeypatch, tmp_path):
    _configure_temp_store(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/workspace/write",
            json={"relative_path": "../outside.txt", "content": "nope"},
        )
    assert response.status_code == 403


def test_rollback_requires_matching_approval(monkeypatch, tmp_path):
    _configure_temp_store(monkeypatch, tmp_path)
    with TestClient(app) as client:
        approval_id = _approve_write(client, "rollback-check.txt", "created")
        written = client.post(
            "/api/workspace/write",
            json={"relative_path": "rollback-check.txt", "content": "created", "approval_id": approval_id},
        )
        assert written.status_code == 200, written.text
        snapshot_id = written.json()["snapshot_id"]
        denied = client.post("/api/workspace/rollback", json={"snapshot_id": snapshot_id, "approval_id": "missing"})
        assert denied.status_code == 403
        wrong = client.post(
            "/api/approvals",
            json={"action": "rollback_snapshot", "payload": {"snapshot_id": "different"}, "reason": "wrong target"},
        )
        assert wrong.status_code == 200
        wrong_id = wrong.json()["id"]
        assert client.post(f"/api/approvals/{wrong_id}/decision?decision=approve").status_code == 200
        mismatch = client.post(
            "/api/workspace/rollback",
            json={"snapshot_id": snapshot_id, "approval_id": wrong_id},
        )
        assert mismatch.status_code == 403
        assert (settings.workspace / "rollback-check.txt").read_text(encoding="utf-8") == "created"
