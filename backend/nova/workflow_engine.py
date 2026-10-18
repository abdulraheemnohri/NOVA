"""Bounded local workflow runner with explicit conditional branches."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from nova.agent_tools import calculator
from nova.audit import append_audit
from nova.config import settings
from nova.knowledge import SearchRequest, search_knowledge

router = APIRouter(prefix="/api/workflows", tags=["workflow engine"])
TOOLS = {"calculator", "knowledge_search"}
CONDITIONS = {"always", "on_success", "on_failure"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _db():
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(settings.database_path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS workflow_definitions(
        id TEXT PRIMARY KEY, name TEXT NOT NULL, steps_json TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS workflow_runs(
        id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, status TEXT NOT NULL,
        steps_json TEXT NOT NULL, current_step INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, finished_at TEXT,
        FOREIGN KEY(workflow_id) REFERENCES workflow_definitions(id))""")
    con.commit()
    return con


class WorkflowStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(min_length=1, max_length=40)
    input: dict[str, Any] = Field(default_factory=dict)
    when: str = "always"


class WorkflowDefinitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=3, max_length=80)
    steps: list[WorkflowStep] = Field(min_length=1, max_length=10)


def _validate(steps):
    cleaned = []
    for index, step in enumerate(steps, 1):
        if step.tool not in TOOLS:
            raise HTTPException(422, f"Step {index}: tool is not allowlisted.")
        if step.when not in CONDITIONS:
            raise HTTPException(422, f"Step {index}: invalid condition.")
        data = dict(step.input)
        if step.tool == "calculator":
            if set(data) != {"expression"} or not isinstance(data.get("expression"), str):
                raise HTTPException(422, f"Step {index}: calculator requires only an expression.")
            value = data["expression"].strip()
            if not value or len(value) > 256:
                raise HTTPException(422, f"Step {index}: expression must be 1–256 characters.")
            try:
                calculator(value)
            except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as exc:
                raise HTTPException(422, f"Step {index}: calculator preflight failed.") from exc
            data["expression"] = value
        else:
            if set(data) != {"query"} or not isinstance(data.get("query"), str):
                raise HTTPException(422, f"Step {index}: knowledge_search requires only a query.")
            value = data["query"].strip()
            if not value or len(value) > 1000:
                raise HTTPException(422, f"Step {index}: query must be 1–1000 characters.")
            data["query"] = value
        cleaned.append({"tool": step.tool, "input": data, "when": step.when})
    return cleaned


def _definition(row):
    item = dict(row)
    item["steps"] = json.loads(item.pop("steps_json"))
    return item


def _run_view(row):
    item = dict(row)
    item["steps"] = json.loads(item.pop("steps_json"))
    return item


@router.get("")
def list_workflows():
    con = _db()
    try:
        rows = con.execute("SELECT * FROM workflow_definitions ORDER BY updated_at DESC LIMIT 200").fetchall()
        return {"workflows": [_definition(row) for row in rows]}
    finally:
        con.close()


@router.post("", status_code=201)
def create_workflow(req: WorkflowDefinitionCreate):
    name = req.name.strip()
    if len(name) < 3:
        raise HTTPException(422, "Workflow name must contain at least three non-space characters.")
    steps = _validate(req.steps)
    workflow_id, timestamp = str(uuid.uuid4()), _now()
    con = _db()
    try:
        con.execute("INSERT INTO workflow_definitions VALUES(?,?,?,?,?)",
                    (workflow_id, name, json.dumps(steps), timestamp, timestamp))
        con.commit()
        row = con.execute("SELECT * FROM workflow_definitions WHERE id=?", (workflow_id,)).fetchone()
    finally:
        con.close()
    append_audit(settings.audit_path, "workflow.created", {
        "workflow_id": workflow_id, "step_count": len(steps), "tools": [s["tool"] for s in steps]})
    return _definition(row)


@router.get("/runs")
def list_runs(limit: int = 20):
    if not 1 <= limit <= 100:
        raise HTTPException(422, "limit must be between 1 and 100.")
    con = _db()
    try:
        rows = con.execute("SELECT * FROM workflow_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return {"runs": [_run_view(row) for row in rows]}
    finally:
        con.close()


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    con = _db()
    try:
        row = con.execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        raise HTTPException(404, "Workflow run not found.")
    return _run_view(row)


def _execute(step):
    if step["tool"] == "calculator":
        return {"result": calculator(step["input"]["expression"])}
    return search_knowledge(SearchRequest(query=step["input"]["query"], limit=5))


@router.post("/{workflow_id}/run", status_code=201)
def run_workflow(workflow_id: str):
    con = _db()
    try:
        definition = con.execute("SELECT * FROM workflow_definitions WHERE id=?", (workflow_id,)).fetchone()
    finally:
        con.close()
    if definition is None:
        raise HTTPException(404, "Workflow not found.")
    # Revalidate persisted data so manual database edits fail closed.
    steps = _validate([WorkflowStep(**step) for step in json.loads(definition["steps_json"])])
    run_id, created = str(uuid.uuid4()), _now()
    con = _db()
    try:
        con.execute("INSERT INTO workflow_runs(id,workflow_id,status,steps_json,current_step,created_at,updated_at) VALUES(?,?,?,'[]',0,?,?)",
                    (run_id, workflow_id, "running", created, created))
        con.commit()
    finally:
        con.close()
    execution, last_status, any_failure = [], "success", False
    append_audit(settings.audit_path, "workflow.run_started", {
        "run_id": run_id, "workflow_id": workflow_id, "step_count": len(steps)})
    try:
        for index, step in enumerate(steps):
            run = (step["when"] == "always"
                   or step["when"] == "on_success" and last_status == "success"
                   or step["when"] == "on_failure" and last_status == "failure")
            record = {"index": index + 1, "tool": step["tool"], "when": step["when"]}
            if not run:
                record.update(status="skipped", reason="condition_not_met")
            else:
                try:
                    record.update(status="success", result=_execute(step))
                    last_status = "success"
                except Exception as exc:
                    record.update(status="failure", error_type=type(exc).__name__, error=str(exc)[:300])
                    last_status, any_failure = "failure", True
            execution.append(record)
            con = _db()
            try:
                con.execute("UPDATE workflow_runs SET steps_json=?,current_step=?,updated_at=? WHERE id=? AND status='running'",
                            (json.dumps(execution, ensure_ascii=False, default=str), index + 1, _now(), run_id))
                con.commit()
            finally:
                con.close()
            append_audit(settings.audit_path, "workflow.step_finished", {
                "run_id": run_id, "workflow_id": workflow_id, "step": index + 1,
                "tool": step["tool"], "status": record["status"]})
        status, finished = ("completed_with_errors" if any_failure else "succeeded"), _now()
        con = _db()
        try:
            con.execute("UPDATE workflow_runs SET status=?,steps_json=?,current_step=?,updated_at=?,finished_at=? WHERE id=? AND status='running'",
                        (status, json.dumps(execution, ensure_ascii=False, default=str), len(execution), finished, finished, run_id))
            con.commit()
            row = con.execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,)).fetchone()
        finally:
            con.close()
        append_audit(settings.audit_path, "workflow.run_finished", {
            "run_id": run_id, "workflow_id": workflow_id, "status": status,
            "steps_failed": sum(s["status"] == "failure" for s in execution)})
        return _run_view(row)
    except Exception:
        con = _db()
        try:
            con.execute("UPDATE workflow_runs SET status='failed',steps_json=?,current_step=?,updated_at=?,finished_at=? WHERE id=? AND status='running'",
                        (json.dumps(execution, ensure_ascii=False, default=str), len(execution), _now(), _now(), run_id))
            con.commit()
        finally:
            con.close()
        raise
