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


def test_duplicate_document_import_returns_consistent_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    initialize_knowledge()
    first = import_document(DocumentImport(source_name="manual.txt", content="same content"))
    second = import_document(DocumentImport(source_name="another-name.txt", content="same content"))
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["id"] == first["id"]
    assert second["source_name"] == "manual.txt"
    assert second["chunks"] == first["chunks"]
    assert second["retrieval"] == "local keyword search; no embeddings"


def test_binary_document_extraction_rejects_unsupported_and_oversized_inputs():
    import pytest
    from fastapi import HTTPException
    from nova.knowledge import extract_document_text, MAX_DOCUMENT_UPLOAD_BYTES
    with pytest.raises(HTTPException) as unsupported:
        extract_document_text("archive.zip", b"data")
    assert unsupported.value.status_code == 415
    with pytest.raises(HTTPException) as oversized:
        extract_document_text("scan.pdf", b"x" * (MAX_DOCUMENT_UPLOAD_BYTES + 1))
    assert oversized.value.status_code == 413


def test_docx_extraction_rejects_invalid_archive():
    import pytest
    from fastapi import HTTPException
    from nova.knowledge import extract_document_text
    with pytest.raises(HTTPException) as invalid:
        extract_document_text("report.docx", b"not-a-zip")
    assert invalid.value.status_code == 422


def test_semantic_retrieval_blends_local_embeddings_with_lexical_scores(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    monkeypatch.setattr(settings, "semantic_retrieval_enabled", True)
    model_dir = tmp_path / "embeddings"
    model_dir.mkdir()
    monkeypatch.setattr(settings, "embedding_model_path", model_dir)
    initialize_knowledge()
    import_document(DocumentImport(source_name="alpha.txt", content="The quick fox jumps over a fence."))
    import_document(DocumentImport(source_name="beta.txt", content="A vehicle transports people along a road."))
    from nova import knowledge
    monkeypatch.setattr(knowledge, "_local_semantic_scores", lambda query, rows: {
        str(row["chunk_id"]): (0.95 if "vehicle" in row["content"] else 0.1)
        for row in rows
    })
    result = search_knowledge(SearchRequest(query="car transportation", limit=5))
    assert result["method"] == "local_hybrid"
    assert result["results"][0]["source"] == "beta.txt"
    assert "semantic_score" in result["results"][0]


def test_semantic_retrieval_stays_keyword_only_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    monkeypatch.setattr(settings, "semantic_retrieval_enabled", False)
    initialize_knowledge()
    import_document(DocumentImport(source_name="manual.txt", content="Local offline processing is enabled."))
    result = search_knowledge(SearchRequest(query="offline processing", limit=5))
    assert result["method"] == "local_keyword"
    assert result["results"][0]["source"] == "manual.txt"



def test_scanned_pdf_ocr_uses_local_tools_with_bounded_arguments(tmp_path, monkeypatch):
    import subprocess
    import sys
    import types
    from pathlib import Path
    from nova import knowledge

    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    monkeypatch.setattr(settings, "pdf_ocr_enabled", True)
    monkeypatch.setattr(settings, "pdf_ocr_max_pages", 2)
    monkeypatch.setattr(settings, "pdf_ocr_timeout_seconds", 30)
    monkeypatch.setattr(settings, "pdf_renderer_cli_path", "/usr/bin/pdftoppm")
    monkeypatch.setattr(settings, "tesseract_cli_path", "/usr/bin/tesseract")
    monkeypatch.setattr(knowledge, "_resolve_pdf_ocr_binary", lambda configured, candidates: configured)
    fake_reader = type("FakeReader", (), {"is_encrypted": False, "pages": [object(), object()]})
    fake_pypdf = types.ModuleType("pypdf")
    fake_pypdf.PdfReader = lambda *args, **kwargs: fake_reader()
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)

    commands = []
    def fake_run(argv, **kwargs):
        commands.append((argv, kwargs))
        if argv[0] == "/usr/bin/pdftoppm":
            assert kwargs["shell"] is False
            assert "-scale-to" in argv and "2000" in argv
            Path(argv[-1] + ".png").write_bytes(b"test image")
            return subprocess.CompletedProcess(argv, 0, "", "")
        assert argv[0] == "/usr/bin/tesseract"
        return subprocess.CompletedProcess(argv, 0, "recognized scanned text", "")
    monkeypatch.setattr(knowledge.subprocess, "run", fake_run)

    extracted = knowledge._ocr_scanned_pdf("scan.pdf", b"fake pdf bytes")
    assert extracted == "recognized scanned text recognized scanned text"
    assert len(commands) == 4
    assert all(call[1]["timeout"] <= 30 for call in commands)


def test_scanned_pdf_ocr_is_opt_in(tmp_path, monkeypatch):
    import pytest
    from fastapi import HTTPException
    from nova import knowledge

    monkeypatch.setattr(settings, "pdf_ocr_enabled", False)
    with pytest.raises(HTTPException) as exc:
        knowledge._ocr_scanned_pdf("scan.pdf", b"unused")
    assert exc.value.status_code == 422



def test_semantic_embedding_vectors_are_persistently_cached(tmp_path, monkeypatch):
    import sys
    import types
    import numpy as np
    from nova import knowledge

    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    monkeypatch.setattr(settings, "semantic_retrieval_enabled", True)
    model_dir = tmp_path / "embeddings"
    model_dir.mkdir()
    (model_dir / "config.json").write_text('{"model":"test"}', encoding="utf-8")
    monkeypatch.setattr(settings, "embedding_model_path", model_dir)
    knowledge.initialize_knowledge()
    knowledge._embedding_model = None
    knowledge._embedding_model_path = None

    class FakeModel:
        def __init__(self):
            self.document_batches = []
        def encode(self, texts, **kwargs):
            texts = list(texts)
            if texts == ["alpha chunk", "beta chunk"]:
                self.document_batches.append(texts)
                return np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
            if texts == ["alpha query"]:
                return np.asarray([[1.0, 0.0]], dtype=np.float32)
            raise AssertionError(f"Unexpected encoding batch: {texts!r}")

    fake_model = FakeModel()
    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = lambda *args, **kwargs: fake_model
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    rows = [
        {"chunk_id": "chunk-a", "content": "alpha chunk"},
        {"chunk_id": "chunk-b", "content": "beta chunk"},
    ]

    first = knowledge._local_semantic_scores("alpha query", rows)
    second = knowledge._local_semantic_scores("alpha query", rows)
    assert first == second
    assert first["chunk-a"] > first["chunk-b"]
    assert fake_model.document_batches == [["alpha chunk", "beta chunk"]]

    con = knowledge._connect()
    try:
        count = con.execute("SELECT count(*) FROM chunk_embeddings").fetchone()[0]
    finally:
        con.close()
    assert count == 2
