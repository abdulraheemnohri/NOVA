from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException

from nova import main
from nova.audit import verify_audit
from nova.config import settings


def test_competing_approval_decisions_only_one_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "approvals.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    created = main.create_approval(main.ApprovalRequest(
        action="workspace_write",
        payload={"relative_path": "race.txt", "content_sha256": "c" * 64},
        reason="Test competing approval decisions",
    ))
    approval_id = created["id"]
    barrier = Barrier(2)

    def decide(decision):
        barrier.wait(timeout=5)
        try:
            return main.decide(approval_id, decision)
        except HTTPException as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, ["approve", "reject"]))

    successes = [result for result in results if isinstance(result, dict)]
    failures = [result for result in results if isinstance(result, HTTPException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].status_code == 409
    assert successes[0]["status"] in {"approved", "rejected"}

    con = main._db()
    try:
        row = con.execute("SELECT status FROM approvals WHERE id=?", (approval_id,)).fetchone()
    finally:
        con.close()
    assert row["status"] == successes[0]["status"]

    valid, count = verify_audit(settings.audit_path)
    assert valid is True
    # Creation plus exactly one successful decision; the losing race emits no decision event.
    assert count == 2
