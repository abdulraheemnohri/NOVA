import hashlib
import json

import pytest
from fastapi import HTTPException

from nova import main
from nova.audit import verify_audit
from nova.config import settings


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    settings.workspace.mkdir(parents=True)
    return settings.workspace


def _approved_write(relative_path, content):
    request = main.ApprovalRequest(
        action="workspace_write",
        payload={
            "relative_path": relative_path,
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        },
        reason="Write reviewed content to a specific workspace path",
    )
    approval = main.create_approval(request)
    decision = main.decide(approval["id"], "approve")
    assert decision["status"] == "approved"
    return approval["id"]


def test_workspace_write_requires_approval(tmp_path, monkeypatch):
    workspace = _isolate(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as exc:
        main.write_file(main.FileWriteRequest(relative_path="notes.txt", content="not approved"))
    assert exc.value.status_code == 403
    assert not (workspace / "notes.txt").exists()


def test_workspace_write_approval_is_bound_to_exact_path_and_content(tmp_path, monkeypatch):
    workspace = _isolate(tmp_path, monkeypatch)
    approved_content = "The reviewed content."
    approval_id = _approved_write("notes/reviewed.txt", approved_content)

    with pytest.raises(HTTPException) as wrong_path:
        main.write_file(main.FileWriteRequest(
            relative_path="notes/other.txt", content=approved_content, approval_id=approval_id
        ))
    assert wrong_path.value.status_code == 403
    assert not (workspace / "notes" / "other.txt").exists()

    with pytest.raises(HTTPException) as wrong_content:
        main.write_file(main.FileWriteRequest(
            relative_path="notes/reviewed.txt", content="changed after approval", approval_id=approval_id
        ))
    assert wrong_content.value.status_code == 403
    assert not (workspace / "notes" / "reviewed.txt").exists()

    con = main._db()
    try:
        approval = con.execute("SELECT status FROM approvals WHERE id=?", (approval_id,)).fetchone()
    finally:
        con.close()
    # Mismatched requests must not consume the valid approval.
    assert approval["status"] == "approved"

    result = main.write_file(main.FileWriteRequest(
        relative_path="notes/reviewed.txt", content=approved_content, approval_id=approval_id
    ))
    assert result["written"] is True
    assert (workspace / "notes" / "reviewed.txt").read_text(encoding="utf-8") == approved_content


def test_workspace_write_approval_is_single_use(tmp_path, monkeypatch):
    workspace = _isolate(tmp_path, monkeypatch)
    content = "one approved write"
    approval_id = _approved_write("one.txt", content)

    first = main.write_file(main.FileWriteRequest(
        relative_path="one.txt", content=content, approval_id=approval_id
    ))
    assert first["written"] is True
    assert (workspace / "one.txt").read_text(encoding="utf-8") == content

    with pytest.raises(HTTPException) as second:
        main.write_file(main.FileWriteRequest(
            relative_path="one.txt", content=content, approval_id=approval_id
        ))
    assert second.value.status_code == 403

    con = main._db()
    try:
        row = con.execute("SELECT status FROM approvals WHERE id=?", (approval_id,)).fetchone()
    finally:
        con.close()
    assert row["status"] == "consumed"
    assert verify_audit(settings.audit_path)[0] is True


def test_approval_payload_hash_is_not_recomputed_from_mutable_request(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    content = "approved"
    approval_id = _approved_write("safe.txt", content)

    # The approval records the exact hash and path; arbitrary payload changes
    # in the request cannot expand the authority of that approval.
    con = main._db()
    try:
        row = con.execute("SELECT payload_json FROM approvals WHERE id=?", (approval_id,)).fetchone()
    finally:
        con.close()
    payload = json.loads(row["payload_json"])
    assert payload == {
        "relative_path": "safe.txt",
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


def test_interrupted_consuming_approval_is_quarantined_on_recovery(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    approval_id = _approved_write("uncertain.txt", "approved content")
    con = main._db()
    try:
        con.execute("UPDATE approvals SET status='consuming' WHERE id=?", (approval_id,))
        con.commit()
    finally:
        con.close()

    assert main._recover_interrupted_approvals() == 1
    con = main._db()
    try:
        row = con.execute("SELECT status FROM approvals WHERE id=?", (approval_id,)).fetchone()
    finally:
        con.close()
    assert row["status"] == "interrupted"
    # Re-running recovery is safe and does not turn an interrupted approval
    # back into an executable/approved state.
    assert main._recover_interrupted_approvals() == 0
    assert verify_audit(settings.audit_path)[0] is True


def test_recovery_only_changes_consuming_approvals(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    approval_id = _approved_write("keep-approved.txt", "content")
    assert main._recover_interrupted_approvals() == 0
    con = main._db()
    try:
        row = con.execute("SELECT status FROM approvals WHERE id=?", (approval_id,)).fetchone()
    finally:
        con.close()
    assert row["status"] == "approved"

def test_concurrent_workspace_write_approval_can_be_claimed_only_once(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    _isolate(tmp_path, monkeypatch)
    content = "one concurrent approved write"
    approval_id = _approved_write("concurrent.txt", content)
    both_at_claim = Barrier(2)
    original_safe_path = main._safe_path

    def synchronize_before_claim(relative_path):
        target = original_safe_path(relative_path)
        both_at_claim.wait(timeout=5)
        return target

    monkeypatch.setattr(main, "_safe_path", synchronize_before_claim)

    def attempt_write():
        try:
            return main.write_file(
                main.FileWriteRequest(
                    relative_path="concurrent.txt",
                    content=content,
                    approval_id=approval_id,
                )
            )
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt_write(), range(2)))

    successful = [result for result in results if isinstance(result, dict) and result.get("written")]
    denied = [result for result in results if result == 403]
    assert len(successful) == 1
    assert len(denied) == 1
    assert (settings.workspace / "concurrent.txt").read_text(encoding="utf-8") == content

    con = main._db()
    try:
        approval = con.execute("SELECT status FROM approvals WHERE id=?", (approval_id,)).fetchone()
        snapshots = con.execute(
            "SELECT COUNT(*) AS count FROM snapshots WHERE relative_path='concurrent.txt'"
        ).fetchone()
    finally:
        con.close()
    assert approval["status"] == "consumed"
    assert snapshots["count"] == 1
