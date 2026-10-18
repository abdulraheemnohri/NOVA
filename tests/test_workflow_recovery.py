import json
import uuid
from datetime import datetime, timezone

from nova.config import settings
import nova.workflow_engine as engine


def test_restart_recovery_marks_running_runs_interrupted_without_replaying(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    definition = engine.create_workflow(engine.WorkflowDefinitionCreate(
        name="Interrupted workflow",
        steps=[engine.WorkflowStep(tool="calculator", input={"expression": "40 + 2"})],
    ))
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    con = engine._db()
    try:
        con.execute(
            "INSERT INTO workflow_runs(id,workflow_id,status,steps_json,current_step,created_at,updated_at) "
            "VALUES(?,?, 'running', ?, 0, ?, ?)",
            (run_id, definition["id"], json.dumps([]), now, now),
        )
        con.commit()
    finally:
        con.close()

    assert engine.recover_interrupted_runs() == 1
    recovered = engine.get_run(run_id)
    assert recovered["status"] == "interrupted"
    assert recovered["finished_at"] is not None
    assert recovered["steps"] == []
    assert engine.recover_interrupted_runs() == 0
