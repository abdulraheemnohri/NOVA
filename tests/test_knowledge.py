from nova.audit import verify_audit
from nova.config import settings
from nova.knowledge import DocumentImport, SearchRequest, import_document, initialize_knowledge, search_knowledge, MemoryCreate, create_memory, delete_memory, GoalCreate, create_goal, GoalStatusUpdate, update_goal_status, list_goals

def test_local_document_import_and_keyword_search(tmp_path, monkeypatch):
    monkeypatch.setattr(settings,"database_path",tmp_path/"nova.sqlite3")
    monkeypatch.setattr(settings,"audit_path",tmp_path/"audit.jsonl")
    initialize_knowledge()
    result=import_document(DocumentImport(source_name="manual.txt",content="NOVA uses local offline models and verified audit records."))
    assert result["chunks"]==1
    search=search_knowledge(SearchRequest(query="offline models",limit=5))
    assert search["results"]
    assert search["results"][0]["source"]=="manual.txt"
    assert "chunk_id" in search["results"][0]

def test_memory_delete_and_goal_create(tmp_path, monkeypatch):
    monkeypatch.setattr(settings,"database_path",tmp_path/"nova.sqlite3")
    monkeypatch.setattr(settings,"audit_path",tmp_path/"audit.jsonl")
    initialize_knowledge()
    memory=create_memory(MemoryCreate(kind="preference",content="Prefer local-only processing"))
    assert delete_memory(memory["id"])["deleted"] is True
    goal=create_goal(GoalCreate(title="Review documents",description="Index local text files"))
    assert goal["status"]=="open"


def test_goal_status_updates_are_persisted_and_audited(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    initialize_knowledge()
    goal = create_goal(GoalCreate(title="Ship NOVA", description="Finish and verify the foundation"))
    updated = update_goal_status(goal["id"], GoalStatusUpdate(status="in_progress"))
    assert updated == {"id": goal["id"], "status": "in_progress"}
    assert list_goals()[0]["status"] == "in_progress"
    valid, count = verify_audit(settings.audit_path)
    assert valid is True
    assert count == 2


def test_goal_status_rejects_unknown_goal(tmp_path, monkeypatch):
    from fastapi import HTTPException
    import pytest
    from nova.knowledge import list_goals
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    initialize_knowledge()
    with pytest.raises(HTTPException) as exc:
        update_goal_status("missing-goal", GoalStatusUpdate(status="completed"))
    assert exc.value.status_code == 404
