import pytest
from fastapi import HTTPException

from nova.config import settings
import nova.workflow_engine as engine


@pytest.fixture
def isolated_workflows(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")


def test_workflow_persists_definition_and_run_checkpoints(isolated_workflows):
    definition = engine.create_workflow(engine.WorkflowDefinitionCreate(
        name="Two calculations",
        steps=[
            engine.WorkflowStep(tool="calculator", input={"expression": "6 * 7"}),
            engine.WorkflowStep(tool="calculator", input={"expression": "10 + 5"}, when="on_success"),
        ],
    ))
    run = engine.run_workflow(definition["id"])
    assert run["status"] == "succeeded"
    assert run["current_step"] == 2
    assert [step["result"]["result"] for step in run["steps"]] == [42, 15]
    assert engine.list_runs()["runs"][0]["id"] == run["id"]


def test_failure_branch_runs_and_original_failure_is_retained(isolated_workflows, monkeypatch):
    definition = engine.create_workflow(engine.WorkflowDefinitionCreate(
        name="Failure branch",
        steps=[
            engine.WorkflowStep(tool="knowledge_search", input={"query": "local knowledge"}),
            engine.WorkflowStep(tool="calculator", input={"expression": "2 + 2"}, when="on_failure"),
        ],
    ))
    monkeypatch.setattr(engine, "search_knowledge", lambda _: (_ for _ in ()).throw(RuntimeError("simulated failure")))
    run = engine.run_workflow(definition["id"])
    assert run["status"] == "completed_with_errors"
    assert run["steps"][0]["status"] == "failure"
    assert run["steps"][1]["status"] == "success"
    assert run["steps"][1]["result"]["result"] == 4


def test_nonmatching_condition_is_skipped(isolated_workflows):
    definition = engine.create_workflow(engine.WorkflowDefinitionCreate(
        name="Skip branch",
        steps=[
            engine.WorkflowStep(tool="calculator", input={"expression": "1 + 1"}),
            engine.WorkflowStep(tool="calculator", input={"expression": "3 + 3"}, when="on_failure"),
        ],
    ))
    run = engine.run_workflow(definition["id"])
    assert run["steps"][1]["status"] == "skipped"
    assert run["status"] == "succeeded"


def test_unknown_tool_rejected_before_execution(isolated_workflows):
    with pytest.raises(HTTPException) as err:
        engine.create_workflow(engine.WorkflowDefinitionCreate(
            name="Bad workflow", steps=[engine.WorkflowStep(tool="shell", input={"command": "id"})]))
    assert err.value.status_code == 422


def test_missing_workflow_returns_404(isolated_workflows):
    with pytest.raises(HTTPException) as err:
        engine.run_workflow("missing")
    assert err.value.status_code == 404
