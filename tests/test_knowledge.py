from nova.config import settings
from nova.knowledge import DocumentImport, SearchRequest, import_document, initialize_knowledge, search_knowledge, MemoryCreate, create_memory, delete_memory, GoalCreate, create_goal

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
