from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import hashlib

from fastapi import HTTPException

from nova import main
from nova.audit import verify_audit
from nova.config import settings


def test_same_approval_cannot_authorize_two_concurrent_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    settings.workspace.mkdir(parents=True)

    relative_path = "concurrent.txt"
    content = "one approved mutation"
    approval = main.create_approval(main.ApprovalRequest(
        action="workspace_write",
        payload={
            "relative_path": relative_path,
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        },
        reason="Allow one exact workspace write",
    ))
    main.decide(approval["id"], "approve")
    barrier = Barrier(2)

    def write():
        barrier.wait(timeout=5)
        try:
            return main.write_file(main.FileWriteRequest(
                relative_path=relative_path,
                content=content,
                approval_id=approval["id"],
            ))
        except HTTPException as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: write(), range(2)))

    successes = [result for result in results if isinstance(result, dict)]
    failures = [result for result in results if isinstance(result, HTTPException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].status_code == 403
    assert (settings.workspace / relative_path).read_text(encoding="utf-8") == content

    con = main._db()
    try:
        approval_row = con.execute(
            "SELECT status FROM approvals WHERE id=?", (approval["id"],)
        ).fetchone()
        snapshot_count = con.execute(
            "SELECT COUNT(*) FROM snapshots WHERE relative_path=?", (relative_path,)
        ).fetchone()[0]
    finally:
        con.close()
    assert approval_row["status"] == "consumed"
    assert snapshot_count == 1
    assert verify_audit(settings.audit_path)[0] is True
