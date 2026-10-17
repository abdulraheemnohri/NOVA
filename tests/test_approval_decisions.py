import pytest
from fastapi import HTTPException

from nova import main
from nova.audit import verify_audit
from nova.config import settings


def test_approval_decision_is_single_use(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "approvals.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")

    created = main.create_approval(
        main.ApprovalRequest(
            action="workspace_write",
            payload={"relative_path": "notes.txt", "content_sha256": "a" * 64},
            reason="Write the reviewed note",
        )
    )
    approval_id = created["id"]

    result = main.decide(approval_id, "approve")
    assert result["status"] == "approved"

    with pytest.raises(HTTPException) as exc:
        main.decide(approval_id, "reject")
    assert exc.value.status_code == 409

    con = main._db()
    try:
        row = con.execute("SELECT status FROM approvals WHERE id=?", (approval_id,)).fetchone()
    finally:
        con.close()
    assert row["status"] == "approved"
    assert verify_audit(settings.audit_path)[0] is True


def test_approval_decision_rejects_invalid_decision(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "approvals.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    created = main.create_approval(
        main.ApprovalRequest(
            action="workspace_write",
            payload={"relative_path": "notes.txt", "content_sha256": "b" * 64},
            reason="Write the reviewed note",
        )
    )
    with pytest.raises(HTTPException) as exc:
        main.decide(created["id"], "maybe")
    assert exc.value.status_code == 422

    con = main._db()
    try:
        row = con.execute("SELECT status FROM approvals WHERE id=?", (created["id"],)).fetchone()
    finally:
        con.close()
    assert row["status"] == "pending"
