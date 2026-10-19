from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import hashlib

from fastapi import HTTPException

from nova import main
from nova.config import settings


def test_snapshot_rollback_is_serialized_and_single_use(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    settings.workspace.mkdir(parents=True)
    target = settings.workspace / "rollback.txt"
    target.write_text("original state", encoding="utf-8")

    new_content = "approved replacement"
    write_approval = main.create_approval(main.ApprovalRequest(
        action="workspace_write",
        payload={
            "relative_path": "rollback.txt",
            "content_sha256": hashlib.sha256(new_content.encode("utf-8")).hexdigest(),
        },
        reason="Prepare a snapshot for rollback concurrency test",
    ))
    main.decide(write_approval["id"], "approve")
    written = main.write_file(main.FileWriteRequest(
        relative_path="rollback.txt",
        content=new_content,
        approval_id=write_approval["id"],
    ))
    snapshot_id = written["snapshot_id"]

    rollback_approval = main.create_approval(main.ApprovalRequest(
        action="rollback_snapshot",
        payload={"snapshot_id": snapshot_id},
        reason="Authorize exactly one rollback of this snapshot",
    ))
    main.decide(rollback_approval["id"], "approve")
    barrier = Barrier(2)

    def rollback():
        barrier.wait(timeout=5)
        try:
            return main.rollback(main.RollbackRequest(
                snapshot_id=snapshot_id,
                approval_id=rollback_approval["id"],
            ))
        except HTTPException as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: rollback(), range(2)))

    successes = [result for result in results if isinstance(result, dict) and result.get("rolled_back")]
    failures = [result for result in results if isinstance(result, HTTPException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].status_code == 409
    assert target.read_text(encoding="utf-8") == "original state"

    con = main._db()
    try:
        snapshot = con.execute(
            "SELECT rolled_back_at FROM snapshots WHERE id=?", (snapshot_id,)
        ).fetchone()
        approval = con.execute(
            "SELECT status FROM approvals WHERE id=?", (rollback_approval["id"],)
        ).fetchone()
    finally:
        con.close()
    assert snapshot["rolled_back_at"] is not None
    assert approval["status"] == "consumed"
