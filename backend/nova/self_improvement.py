"""User-reviewable self-created skills and tool proposals.

Generated content is data, never Python/JavaScript and never executable code.
Only existing, explicitly registered safe tool primitives may be proposed.
"""
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from nova.audit import append_audit
from nova.config import settings
from nova.agent_tools import calculator
from nova.knowledge import SearchRequest, search_knowledge

router = APIRouter(prefix="/api/self", tags=["self improvement"])
SAFE_PRIMITIVES = {
    "calculator": {"expression": "string"},
    "knowledge_search": {"query": "string"},
    "text_stats": {"text": "string"},
    "json_format": {"json": "string"},
    "base64_encode": {"text": "string"},
    "base64_decode": {"encoded": "string"},
    "csv_summary": {"csv": "string"},
    "markdown_outline": {"markdown": "string"},
}


def db():
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(settings.database_path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS self_skills(
        id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
        instructions TEXT NOT NULL, tags_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft', version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS self_skill_runs(
        id TEXT PRIMARY KEY, skill_id TEXT NOT NULL, status TEXT NOT NULL,
        steps_json TEXT NOT NULL, results_json TEXT NOT NULL, error TEXT,
        created_at TEXT NOT NULL, finished_at TEXT,
        FOREIGN KEY(skill_id) REFERENCES self_skills(id))""")
    run_columns = {str(row[1]) for row in con.execute("PRAGMA table_info(self_skill_runs)").fetchall()}
    if "current_step" not in run_columns:
        con.execute("ALTER TABLE self_skill_runs ADD COLUMN current_step INTEGER NOT NULL DEFAULT 0")
    if "cancel_requested" not in run_columns:
        con.execute("ALTER TABLE self_skill_runs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0")
    if "attempts_json" not in run_columns:
        con.execute("ALTER TABLE self_skill_runs ADD COLUMN attempts_json TEXT NOT NULL DEFAULT '[]'")
    con.execute("""CREATE TABLE IF NOT EXISTS self_workflows(
        id TEXT PRIMARY KEY, skill_id TEXT NOT NULL, name TEXT NOT NULL,
        steps_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        FOREIGN KEY(skill_id) REFERENCES self_skills(id))""")
    con.execute("""CREATE TABLE IF NOT EXISTS self_tool_proposals(
        id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
        primitive TEXT NOT NULL, input_schema_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL)""")
    con.commit()
    return con


def now():
    return datetime.now(timezone.utc).isoformat()


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:60]


class SkillCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=3, max_length=80)
    description: str = Field(min_length=3, max_length=500)
    instructions: str = Field(min_length=10, max_length=12000)
    tags: list[str] = Field(default_factory=list, max_length=12)


class SkillUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    name: str = Field(min_length=3, max_length=80)
    description: str = Field(min_length=3, max_length=500)
    instructions: str = Field(min_length=10, max_length=12000)
    tags: list[str] = Field(default_factory=list, max_length=12)

class SkillImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: str = Field(pattern=r"^nova-skill-v1$")
    skill: SkillCreate


class ToolProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=3, max_length=60)
    description: str = Field(min_length=3, max_length=500)
    primitive: str = Field(min_length=1, max_length=60)
    input_schema: dict[str, str] = Field(min_length=1, max_length=8)


def row_skill(row):
    item = dict(row)
    item["tags"] = json.loads(item.pop("tags_json"))
    return item


def row_tool(row):
    item = dict(row)
    item["input_schema"] = json.loads(item.pop("input_schema_json"))
    return item


@router.get("/skills")
def list_skills(q: str | None = None, tag: str | None = None, status: str | None = None):
    """Search and filter skills without changing their state."""
    if q is not None and len(q) > 200:
        raise HTTPException(422, "Search query is limited to 200 characters.")
    if status is not None and status not in {"draft", "active", "disabled"}:
        raise HTTPException(422, "Status filter must be draft, active, or disabled.")
    clean_tag = tag.strip().lower() if tag else None
    con = db()
    try:
        rows = con.execute("SELECT * FROM self_skills ORDER BY updated_at DESC LIMIT 1000").fetchall()
        skills = [row_skill(row) for row in rows]
        needle = q.strip().casefold() if q else ""
        if needle:
            skills = [item for item in skills if needle in " ".join(
                [item["name"], item["description"], item["instructions"], *item["tags"]]
            ).casefold()]
        if clean_tag:
            skills = [item for item in skills if clean_tag in item["tags"]]
        if status:
            skills = [item for item in skills if item["status"] == status]
        return {"skills": skills[:200], "total": len(skills),
                "filters": {"q": q, "tag": clean_tag, "status": status}}
    finally:
        con.close()


@router.get("/skills/{skill_id}/export")
def export_skill(skill_id: str):
    """Export only editable skill content; imports always become drafts."""
    con = db()
    try:
        row = con.execute("SELECT * FROM self_skills WHERE id=?", (skill_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Skill not found.")
        skill = row_skill(row)
        payload = {key: skill[key] for key in ("name", "description", "instructions", "tags")}
        return {"format": "nova-skill-v1", "skill": payload}
    finally:
        con.close()


@router.post("/skills/import", status_code=201)
def import_skill(req: SkillImport):
    """Import a portable skill as a new draft, never as an active skill."""
    return create_skill(req.skill)


@router.post("/skills", status_code=201)
def create_skill(req: SkillCreate):
    name = req.name.strip()
    description = req.description.strip()
    instructions = req.instructions.strip()
    if not slug(name) or not instructions:
        raise HTTPException(422, "Skill name and instructions must contain usable text.")
    tags = []
    for tag in req.tags:
        clean = tag.strip().lower()
        if not clean or len(clean) > 40 or any(ord(ch) < 32 for ch in clean):
            raise HTTPException(422, "Tags must be 1–40 printable characters.")
        if clean not in tags:
            tags.append(clean)
    skill_id = str(uuid.uuid4())
    timestamp = now()
    con = db()
    try:
        con.execute(
            "INSERT INTO self_skills(id,name,description,instructions,tags_json,status,version,created_at,updated_at) VALUES(?,?,?,?,?,'draft',1,?,?)",
            (skill_id, name, description, instructions, json.dumps(tags), timestamp, timestamp),
        )
        con.commit()
        row = con.execute("SELECT * FROM self_skills WHERE id=?", (skill_id,)).fetchone()
    finally:
        con.close()
    append_audit(settings.audit_path, "self.skill.created", {"skill_id": skill_id, "name": name, "status": "draft"})
    return row_skill(row)


@router.put("/skills/{skill_id}")
def update_skill(skill_id: str, req: SkillUpdate):
    """Update a draft/disabled skill using optimistic version checking."""
    name = req.name.strip()
    description = req.description.strip()
    instructions = req.instructions.strip()
    if not slug(name) or not instructions:
        raise HTTPException(422, "Skill name and instructions must contain usable text.")
    tags = []
    for tag in req.tags:
        clean = tag.strip().lower()
        if not clean or len(clean) > 40 or any(ord(ch) < 32 for ch in clean):
            raise HTTPException(422, "Tags must be 1–40 printable characters.")
        if clean not in tags:
            tags.append(clean)
    con = db()
    try:
        row = con.execute("SELECT * FROM self_skills WHERE id=?", (skill_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Skill not found.")
        if row["status"] == "active":
            raise HTTPException(409, "Disable the skill before editing it.")
        if row["status"] not in ("draft", "disabled"):
            raise HTTPException(409, "Only draft or disabled skills can be edited.")
        if int(row["version"]) != req.expected_version:
            raise HTTPException(409, "Skill version changed; refresh and review the latest version before saving.")
        timestamp = now()
        cur = con.execute(
            """UPDATE self_skills SET name=?,description=?,instructions=?,tags_json=?,
            version=version+1,updated_at=? WHERE id=? AND version=? AND status IN ('draft','disabled')""",
            (name, description, instructions, json.dumps(tags), timestamp, skill_id, req.expected_version),
        )
        if cur.rowcount != 1:
            raise HTTPException(409, "Skill changed while saving; refresh and retry.")
        con.commit()
        updated = con.execute("SELECT * FROM self_skills WHERE id=?", (skill_id,)).fetchone()
    finally:
        con.close()
    append_audit(settings.audit_path, "self.skill.updated", {
        "skill_id": skill_id, "version": updated["version"], "status": updated["status"]
    })
    return row_skill(updated)


@router.post("/skills/{skill_id}/activate")
def activate_skill(skill_id: str):
    con = db()
    try:
        cur = con.execute(
            "UPDATE self_skills SET status='active',version=version+1,updated_at=? WHERE id=? AND status IN ('draft','disabled')",
            (now(), skill_id),
        )
        con.commit()
        row = con.execute("SELECT * FROM self_skills WHERE id=?", (skill_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        raise HTTPException(404, "Skill not found.")
    if cur.rowcount != 1:
        raise HTTPException(409, "Only draft or disabled skills can be activated.")
    append_audit(settings.audit_path, "self.skill.activated", {"skill_id": skill_id, "version": row["version"]})
    return row_skill(row)


@router.post("/skills/{skill_id}/disable")
def disable_skill(skill_id: str):
    """Disable a skill without deleting its definition or execution history."""
    con = db()
    try:
        cur = con.execute(
            "UPDATE self_skills SET status='disabled',version=version+1,updated_at=? WHERE id=? AND status='active'",
            (now(), skill_id),
        )
        con.commit()
        row = con.execute("SELECT * FROM self_skills WHERE id=?", (skill_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        raise HTTPException(404, "Skill not found.")
    if cur.rowcount != 1:
        raise HTTPException(409, "Only active skills can be disabled.")
    append_audit(settings.audit_path, "self.skill.disabled", {"skill_id": skill_id, "version": row["version"]})
    return row_skill(row)


@router.get("/tools")
def list_tool_proposals():
    con = db()
    try:
        rows = con.execute("SELECT * FROM self_tool_proposals ORDER BY updated_at DESC LIMIT 200").fetchall()
        return {"tools": [row_tool(row) for row in rows], "available_primitives": sorted(SAFE_PRIMITIVES),
                "executable_generated_code": False}
    finally:
        con.close()


@router.post("/tools", status_code=201)
def create_tool_proposal(req: ToolProposalCreate):
    name = req.name.strip()
    description = req.description.strip()
    primitive = req.primitive.strip()
    if primitive not in SAFE_PRIMITIVES:
        raise HTTPException(422, "Only existing safe primitives may be proposed; new code is never executed.")
    expected = SAFE_PRIMITIVES[primitive]
    schema = req.input_schema
    if schema != expected:
        raise HTTPException(422, "Input schema must exactly match the selected primitive's bounded schema.")
    if not slug(name) or not description:
        raise HTTPException(422, "Tool name and description must contain usable text.")
    tool_id = str(uuid.uuid4())
    timestamp = now()
    con = db()
    try:
        con.execute(
            "INSERT INTO self_tool_proposals(id,name,description,primitive,input_schema_json,status,created_at,updated_at) VALUES(?,?,?,?,?,'draft',?,?)",
            (tool_id, name, description, primitive, json.dumps(schema, sort_keys=True), timestamp, timestamp),
        )
        con.commit()
        row = con.execute("SELECT * FROM self_tool_proposals WHERE id=?", (tool_id,)).fetchone()
    finally:
        con.close()
    append_audit(settings.audit_path, "self.tool.proposed", {"tool_id": tool_id, "name": name, "primitive": primitive, "status": "draft"})
    return row_tool(row)


@router.post("/tools/{tool_id}/review")
def review_tool_proposal(tool_id: str):
    con = db()
    try:
        cur = con.execute(
            "UPDATE self_tool_proposals SET status='reviewed',updated_at=? WHERE id=? AND status='draft'",
            (now(), tool_id),
        )
        con.commit()
        row = con.execute("SELECT * FROM self_tool_proposals WHERE id=?", (tool_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        raise HTTPException(404, "Tool proposal not found.")
    if cur.rowcount != 1:
        raise HTTPException(409, "Only draft tool proposals can be reviewed.")
    append_audit(settings.audit_path, "self.tool.reviewed", {"tool_id": tool_id, "primitive": row["primitive"],
        "status": "reviewed", "executable_generated_code": False})
    return row_tool(row)


class SkillStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(min_length=1, max_length=60)
    input: dict[str, str] = Field(min_length=1, max_length=1)
    retries: int = Field(default=0, ge=0, le=3)


class SkillRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[SkillStep] = Field(min_length=1, max_length=5)


def _validate_step(step: SkillStep) -> dict:
    if step.tool == "calculator":
        if set(step.input) != {"expression"}:
            raise HTTPException(422, "Calculator step requires exactly the expression field.")
        expression = step.input["expression"]
        if len(expression) > 256:
            raise HTTPException(422, "Calculator expression is too long.")
        try:
            calculator(expression)
        except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as exc:
            raise HTTPException(422, f"Invalid calculator step: {exc}") from exc
        return {"tool": step.tool, "input": {"expression": expression}, "retries": step.retries}
    if step.tool == "knowledge_search":
        if set(step.input) != {"query"}:
            raise HTTPException(422, "Knowledge search step requires exactly the query field.")
        query = step.input["query"].strip()
        if not query or len(query) > 1000:
            raise HTTPException(422, "Knowledge query must contain 1–1000 characters.")
        return {"tool": step.tool, "input": {"query": query}, "retries": step.retries}
    if step.tool == "text_stats":
        if set(step.input) != {"text"}:
            raise HTTPException(422, "Text statistics step requires exactly the text field.")
        value = step.input["text"]
        if len(value) > 10000:
            raise HTTPException(422, "Text input is limited to 10000 characters.")
        return {"tool": step.tool, "input": {"text": value}, "retries": step.retries}
    raise HTTPException(422, "Unsupported skill tool; default deny.")


@router.get("/skills/{skill_id}/runs")
def list_skill_runs(skill_id: str):
    con = db()
    try:
        if con.execute("SELECT 1 FROM self_skills WHERE id=?", (skill_id,)).fetchone() is None:
            raise HTTPException(404, "Skill not found.")
        rows = con.execute(
            "SELECT * FROM self_skill_runs WHERE skill_id=? ORDER BY created_at DESC LIMIT 50",
            (skill_id,),
        ).fetchall()
        runs = []
        for row in rows:
            item = dict(row)
            item["steps"] = json.loads(item.pop("steps_json"))
            item["results"] = json.loads(item.pop("results_json"))
            item["attempts"] = json.loads(item.pop("attempts_json", "[]") or "[]")
            runs.append(item)
        return {"runs": runs}
    finally:
        con.close()


@router.post("/skills/{skill_id}/runs/{run_id}/resume", status_code=201)
def resume_skill_run(skill_id: str, run_id: str):
    con = db()
    try:
        row = con.execute(
            "SELECT r.*,s.status AS skill_status,s.version AS skill_version FROM self_skill_runs r "
            "JOIN self_skills s ON s.id=r.skill_id WHERE r.id=? AND r.skill_id=?", (run_id, skill_id)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Skill run not found.")
        if row["skill_status"] != "active":
            raise HTTPException(409, "Only runs belonging to an active skill can be resumed.")
        if row["status"] not in {"interrupted", "failed"}:
            raise HTTPException(409, "Only interrupted or failed runs can be resumed; cancelled runs are not resumed.")
        planned_raw = json.loads(row["steps_json"])
        results = json.loads(row["results_json"])
        checkpoint = int(row["current_step"])
        if checkpoint < 0 or checkpoint > len(planned_raw) or checkpoint != len(results):
            raise HTTPException(409, "Saved checkpoint is inconsistent; run cannot be resumed safely.")
    finally:
        con.close()
    # Revalidate the entire saved plan before continuing from its durable checkpoint.
    planned = [_validate_step(SkillStep(tool=step["tool"], input=step["input"], retries=step.get("retries", 0))) for step in planned_raw]
    con = db()
    try:
        cur = con.execute(
            "UPDATE self_skill_runs SET status='running',cancel_requested=0,error=NULL,finished_at=NULL WHERE id=? AND skill_id=? AND status IN ('interrupted','failed')",
            (run_id, skill_id),
        )
        con.commit()
    finally:
        con.close()
    if cur.rowcount != 1:
        raise HTTPException(409, "Run state changed; refresh history before resuming.")
    append_audit(settings.audit_path, "self.skill.run_resumed", {
        "run_id": run_id, "skill_id": skill_id, "checkpoint_step": checkpoint, "remaining_steps": len(planned) - checkpoint,
    })
    return _continue_skill_run(skill_id, run_id, planned, results, checkpoint, row["skill_version"])


@router.post("/skills/{skill_id}/runs/{run_id}/cancel")
def cancel_skill_run(skill_id: str, run_id: str):
    con = db()
    try:
        row = con.execute("SELECT status,cancel_requested FROM self_skill_runs WHERE id=? AND skill_id=?", (run_id, skill_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Skill run not found.")
        if row["status"] != "running":
            raise HTTPException(409, "Only a running skill execution can be cancelled.")
        if not row["cancel_requested"]:
            con.execute("UPDATE self_skill_runs SET cancel_requested=1 WHERE id=? AND skill_id=? AND status='running'", (run_id, skill_id))
            con.commit()
    finally:
        con.close()
    append_audit(settings.audit_path, "self.skill.cancel_requested", {"skill_id": skill_id, "run_id": run_id})
    return {"run_id": run_id, "skill_id": skill_id, "status": "cancel_requested", "cancel_requested": True,
            "message": "Cancellation is checked between steps; an already-running safe step may finish."}


def _continue_skill_run(skill_id: str, run_id: str, planned: list[dict], results: list, start_index: int, skill_version: int):
    con = db()
    try:
        row = con.execute("SELECT attempts_json FROM self_skill_runs WHERE id=?", (run_id,)).fetchone()
        attempts = json.loads(row["attempts_json"] or "[]") if row else []
    finally:
        con.close()
    try:
        for index in range(start_index, len(planned)):
            step = planned[index]
            con = db()
            try:
                run_state = con.execute("SELECT status,cancel_requested FROM self_skill_runs WHERE id=?", (run_id,)).fetchone()
            finally:
                con.close()
            if run_state is None or run_state["status"] != "running" or run_state["cancel_requested"]:
                break
            last_error = None
            result = None
            for attempt_number in range(1, int(step.get("retries", 0)) + 2):
                attempt = {"step": index + 1, "attempt": attempt_number, "tool": step["tool"], "status": "running"}
                attempts.append(attempt)
                con = db()
                try:
                    con.execute("UPDATE self_skill_runs SET attempts_json=? WHERE id=? AND status='running'",
                        (json.dumps(attempts, ensure_ascii=False, default=str), run_id))
                    con.commit()
                finally:
                    con.close()
                try:
                    if step["tool"] == "calculator":
                        result = {"result": calculator(step["input"]["expression"])}
                    elif step["tool"] == "knowledge_search":
                        result = search_knowledge(SearchRequest(query=step["input"]["query"], limit=5))
                    else:
                        value = step["input"]["text"]
                        result = {"characters": len(value), "words": len(value.split()), "lines": len(value.splitlines()) if value else 0}
                    attempt["status"] = "succeeded"
                    attempt["finished_at"] = now()
                    last_error = None
                    con = db()
                    try:
                        con.execute("UPDATE self_skill_runs SET attempts_json=? WHERE id=? AND status='running'",
                            (json.dumps(attempts, ensure_ascii=False, default=str), run_id))
                        con.commit()
                    finally:
                        con.close()
                    break
                except Exception as exc:
                    last_error = exc
                    attempt["status"] = "failed"
                    attempt["error"] = str(exc)[:300]
                    attempt["finished_at"] = now()
                    con = db()
                    try:
                        con.execute("UPDATE self_skill_runs SET attempts_json=? WHERE id=? AND status='running'",
                            (json.dumps(attempts, ensure_ascii=False, default=str), run_id))
                        con.commit()
                    finally:
                        con.close()
                    if attempt_number <= int(step.get("retries", 0)):
                        append_audit(settings.audit_path, "self.skill.step_retry", {
                            "run_id": run_id, "skill_id": skill_id, "step": index + 1,
                            "attempt": attempt_number, "error_type": type(exc).__name__,
                        })
            if last_error is not None:
                raise last_error
            results.append({"tool": step["tool"], "result": result, "attempt_count": sum(
                1 for attempt in attempts if attempt.get("step") == index + 1
            )})
            con = db()
            try:
                con.execute("UPDATE self_skill_runs SET results_json=?,current_step=?,attempts_json=? WHERE id=? AND status='running'",
                    (json.dumps(results, ensure_ascii=False, default=str), index + 1,
                     json.dumps(attempts, ensure_ascii=False, default=str), run_id))
                con.commit()
            finally:
                con.close()
        finished = now()
        con = db()
        try:
            state = con.execute("SELECT cancel_requested FROM self_skill_runs WHERE id=?", (run_id,)).fetchone()
            cancelled = bool(state and state["cancel_requested"])
            final_status = "cancelled" if cancelled else "succeeded"
            con.execute("UPDATE self_skill_runs SET status=?,results_json=?,current_step=?,attempts_json=?,finished_at=? WHERE id=? AND status='running'",
                (final_status, json.dumps(results, ensure_ascii=False, default=str), len(results),
                 json.dumps(attempts, ensure_ascii=False, default=str), finished, run_id))
            con.commit()
        finally:
            con.close()
        if cancelled:
            append_audit(settings.audit_path, "self.skill.run_cancelled", {"run_id": run_id, "skill_id": skill_id, "completed_steps": len(results)})
        else:
            append_audit(settings.audit_path, "self.skill.run_succeeded", {
                "run_id": run_id, "skill_id": skill_id, "skill_version": skill_version,
                "step_count": len(planned), "tools": [step["tool"] for step in planned],
                "attempt_count": len(attempts),
            })
        return {"run_id": run_id, "skill_id": skill_id, "status": final_status,
                "cancelled": cancelled, "current_step": len(results), "results": results, "attempts": attempts}
    except Exception as exc:
        finished = now()
        con = db()
        try:
            con.execute("UPDATE self_skill_runs SET status='failed',results_json=?,current_step=?,attempts_json=?,error=?,finished_at=? WHERE id=? AND status='running'",
                (json.dumps(results, ensure_ascii=False, default=str), len(results),
                 json.dumps(attempts, ensure_ascii=False, default=str), str(exc)[:500], finished, run_id))
            con.commit()
        finally:
            con.close()
        append_audit(settings.audit_path, "self.skill.run_failed", {
            "run_id": run_id, "skill_id": skill_id, "completed_steps": len(results),
            "attempt_count": len(attempts), "error_type": type(exc).__name__,
        })
        raise HTTPException(422, "Skill run failed; inspect run history for completed safe steps and attempt history.") from exc


def recover_interrupted_skill_runs():
    """Mark runs left active by a process restart; keep checkpoints and never replay automatically."""
    con = db()
    try:
        rows = con.execute("SELECT id,skill_id,current_step FROM self_skill_runs WHERE status='running'").fetchall()
        timestamp = now()
        for row in rows:
            con.execute(
                "UPDATE self_skill_runs SET status='interrupted',error=?,finished_at=? WHERE id=? AND status='running'",
                ("Interrupted by process restart; checkpoint preserved.", timestamp, row["id"]),
            )
        con.commit()
    finally:
        con.close()
    for row in rows:
        append_audit(settings.audit_path, "self.skill.run_interrupted", {
            "run_id": row["id"], "skill_id": row["skill_id"], "checkpoint_step": row["current_step"],
        })
    return {"interrupted": len(rows), "run_ids": [row["id"] for row in rows]}


@router.post("/skills/{skill_id}/run", status_code=201)
def run_skill(skill_id: str, req: SkillRunRequest):
    # Validate the entire structured plan before running any step. Only safe
    # read-only primitives are supported; natural-language skill text is not code.
    planned = [_validate_step(step) for step in req.steps]
    con = db()
    try:
        skill = con.execute("SELECT id,name,status,version FROM self_skills WHERE id=?", (skill_id,)).fetchone()
    finally:
        con.close()
    if skill is None:
        raise HTTPException(404, "Skill not found.")
    if skill["status"] != "active":
        raise HTTPException(409, "Only active skills can run.")
    run_id = str(uuid.uuid4())
    timestamp = now()
    con = db()
    try:
        con.execute(
            "INSERT INTO self_skill_runs(id,skill_id,status,steps_json,results_json,created_at) VALUES(?,?,'running',?,'[]',?)",
            (run_id, skill_id, json.dumps(planned), timestamp),
        )
        con.commit()
    finally:
        con.close()
    return _continue_skill_run(skill_id, run_id, planned, [], 0, skill["version"])


class WorkflowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=3, max_length=80)
    steps: list[SkillStep] = Field(min_length=1, max_length=5)


def _row_workflow(row):
    item = dict(row)
    item["steps"] = json.loads(item.pop("steps_json"))
    return item


@router.get("/workflows")
def list_workflows():
    con = db()
    try:
        rows = con.execute(
            "SELECT w.*,s.name AS skill_name,s.status AS skill_status FROM self_workflows w "
            "JOIN self_skills s ON s.id=w.skill_id ORDER BY w.updated_at DESC LIMIT 200"
        ).fetchall()
        return {"workflows": [_row_workflow(row) for row in rows]}
    finally:
        con.close()


@router.post("/workflows", status_code=201)
def create_workflow(req: WorkflowCreate):
    name = req.name.strip()
    if not name:
        raise HTTPException(422, "Workflow name must contain usable text.")
    planned = [_validate_step(step) for step in req.steps]
    con = db()
    try:
        skill = con.execute("SELECT id,status FROM self_skills WHERE id=?", (req.skill_id,)).fetchone()
    finally:
        con.close()
    if skill is None:
        raise HTTPException(404, "Skill not found.")
    if skill["status"] != "active":
        raise HTTPException(409, "A workflow can only be saved for an active skill.")
    workflow_id = str(uuid.uuid4())
    timestamp = now()
    con = db()
    try:
        con.execute(
            "INSERT INTO self_workflows(id,skill_id,name,steps_json,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (workflow_id, req.skill_id, name, json.dumps(planned), timestamp, timestamp),
        )
        con.commit()
        row = con.execute(
            "SELECT w.*,s.name AS skill_name,s.status AS skill_status FROM self_workflows w "
            "JOIN self_skills s ON s.id=w.skill_id WHERE w.id=?", (workflow_id,)
        ).fetchone()
    finally:
        con.close()
    append_audit(settings.audit_path, "self.workflow.created", {
        "workflow_id": workflow_id, "skill_id": req.skill_id, "step_count": len(planned),
        "tools": [step["tool"] for step in planned],
    })
    return _row_workflow(row)


@router.post("/workflows/{workflow_id}/run", status_code=201)
def run_saved_workflow(workflow_id: str):
    con = db()
    try:
        row = con.execute("SELECT * FROM self_workflows WHERE id=?", (workflow_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        raise HTTPException(404, "Workflow not found.")
    steps = [SkillStep(tool=step["tool"], input=step["input"]) for step in json.loads(row["steps_json"])]
    result = run_skill(row["skill_id"], SkillRunRequest(steps=steps))
    append_audit(settings.audit_path, "self.workflow.run", {
        "workflow_id": workflow_id, "skill_id": row["skill_id"], "run_id": result["run_id"],
        "step_count": len(steps),
    })
    return {"workflow_id": workflow_id, **result}
