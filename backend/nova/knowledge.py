"""Local text knowledge, memories, goals, and optional offline hybrid retrieval.

Keyword search is the default. Semantic retrieval is opt-in and loads only a local
SentenceTransformers model directory; failures fall back to lexical search.
"""
import hashlib, html, io, json, re, sqlite3, uuid, zipfile
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from nova.config import settings
from nova.audit import append_audit

router=APIRouter(prefix="/api")

# Optional embeddings are loaded strictly from a local directory. The default is
# disabled so installations remain dependency-free and fully offline.
_embedding_model = None
_embedding_model_path: str | None = None


def _local_semantic_scores(query: str, rows) -> dict[str, float] | None:
    global _embedding_model, _embedding_model_path
    if not settings.semantic_retrieval_enabled:
        return None
    model_path = settings.embedding_model_path.expanduser()
    if not model_path.is_dir():
        return None
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
        path = str(model_path.resolve())
        if _embedding_model is None or _embedding_model_path != path:
            _embedding_model = SentenceTransformer(
                path, device="cpu", local_files_only=True, trust_remote_code=False
            )
            _embedding_model_path = path
        texts = [str(row["content"]) for row in rows]
        if not texts:
            return {}
        vectors = _embedding_model.encode(
            texts, normalize_embeddings=True, convert_to_numpy=True,
            show_progress_bar=False,
        )
        query_vector = _embedding_model.encode(
            [query], normalize_embeddings=True, convert_to_numpy=True,
            show_progress_bar=False,
        )[0]
        scores = np.asarray(vectors) @ np.asarray(query_vector)
        return {str(row["chunk_id"]): max(0.0, min(1.0, float(score)))
                for row, score in zip(rows, scores)}
    except (ImportError, OSError, ValueError, RuntimeError, TypeError):
        # Optional embeddings must never take down local keyword search.
        return None

def _connect():
    settings.database_path.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(settings.database_path); con.row_factory=sqlite3.Row
    con.executescript("""
    CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, source_name TEXT NOT NULL, content_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS document_chunks(id TEXT PRIMARY KEY, document_id TEXT NOT NULL, chunk_index INTEGER NOT NULL, content TEXT NOT NULL, FOREIGN KEY(document_id) REFERENCES documents(id));
    CREATE TABLE IF NOT EXISTS memories(id TEXT PRIMARY KEY, kind TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS goals(id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
    """)
    con.commit(); return con
def initialize_knowledge():
    con=_connect(); con.close()
def _audit(event, details):
    append_audit(settings.audit_path,event,details)
def _clean_text(source_name:str, content:str)->str:
    suffix=Path(source_name).suffix.lower()
    if suffix not in {".txt",".md",".markdown",".csv",".json",".html",".htm",".pdf",".docx"}:
        raise HTTPException(415,"Supported formats: TXT, Markdown, CSV, JSON, HTML, PDF and DOCX.")
    if suffix in {".html",".htm"}:
        content=re.sub(r"(?is)<(script|style).*?>.*?</\1>"," ",content)
        content=re.sub(r"(?s)<[^>]+>"," ",content)
        content=html.unescape(content)
    return re.sub(r"\s+"," ",content).strip()
def _chunks(text:str, size:int=1200, overlap:int=150)->list[str]:
    if not text: return []
    result=[]; start=0
    while start<len(text):
        end=min(len(text),start+size); result.append(text[start:end])
        if end==len(text): break
        start=end-overlap
    return result

MAX_DOCUMENT_UPLOAD_BYTES = 20_000_000
MAX_EXTRACTED_TEXT_CHARS = 2_000_000


def extract_document_text(filename: str, data: bytes) -> str:
    """Extract inert text from bounded PDF/DOCX bytes; never execute embedded content."""
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        raise HTTPException(415, "Binary upload endpoint accepts PDF or DOCX only.")
    if not data or len(data) > MAX_DOCUMENT_UPLOAD_BYTES:
        raise HTTPException(413, "Document must be non-empty and no larger than 20 MB.")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise HTTPException(503, "PDF extraction requires the optional pypdf dependency.") from exc
        try:
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise HTTPException(422, "Encrypted PDFs are not supported.")
            if len(reader.pages) > 500:
                raise HTTPException(413, "PDF exceeds the 500-page extraction limit.")
            parts = []
            total = 0
            for page in reader.pages:
                page_text = page.extract_text() or ""
                total += len(page_text)
                if total > MAX_EXTRACTED_TEXT_CHARS:
                    raise HTTPException(413, "Extracted text exceeds the 2 MB text limit.")
                parts.append(page_text)
            extracted = "\n".join(parts)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, "PDF could not be parsed as a valid document.") from exc
    else:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                infos = archive.infolist()
                if len(infos) > 2000 or sum(item.file_size for item in infos) > 50_000_000:
                    raise HTTPException(413, "DOCX archive exceeds safe extraction limits.")
                for item in infos:
                    member = item.filename.replace("\\", "/")
                    if member.startswith("/") or any(part == ".." for part in member.split("/")):
                        raise HTTPException(422, "DOCX contains an unsafe archive path.")
                    if "vbaproject" in member.lower():
                        raise HTTPException(415, "Macro-enabled documents are not supported.")
                if "word/document.xml" not in {item.filename for item in infos}:
                    raise HTTPException(422, "DOCX is missing its main document body.")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, "DOCX could not be parsed as a valid archive.") from exc
        try:
            from docx import Document
        except ImportError as exc:
            raise HTTPException(503, "DOCX extraction requires the optional python-docx dependency.") from exc
        try:
            document = Document(io.BytesIO(data))
            parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text]
            for table in document.tables:
                for row in table.rows:
                    parts.append(" | ".join(cell.text for cell in row.cells))
            extracted = "\n".join(parts)
        except Exception as exc:
            raise HTTPException(422, "DOCX could not be parsed as a valid document.") from exc
    if len(extracted) > MAX_EXTRACTED_TEXT_CHARS:
        raise HTTPException(413, "Extracted text exceeds the 2 MB text limit.")
    return re.sub(r"\s+", " ", extracted).strip()


@router.post("/documents/import-file")
async def import_document_file(file: UploadFile = File(...)):
    filename = Path(file.filename or "upload").name
    if not filename or filename in {".", ".."}:
        raise HTTPException(422, "A valid local filename is required.")
    data = await file.read(MAX_DOCUMENT_UPLOAD_BYTES + 1)
    if len(data) > MAX_DOCUMENT_UPLOAD_BYTES:
        raise HTTPException(413, "Upload exceeds the 20 MB limit.")
    extracted = extract_document_text(filename, data)
    if not extracted:
        raise HTTPException(422, "Document contains no extractable text. Scanned PDFs need a local OCR adapter.")
    result = import_document(DocumentImport(source_name=filename, content=extracted))
    _audit("document.file_extracted", {
        "document_id": result["id"], "source_name": filename,
        "file_sha256": hashlib.sha256(data).hexdigest(), "extracted_chars": len(extracted),
    })
    return {**result, "extracted_chars": len(extracted), "extraction": "local text extraction; no OCR"}

class DocumentImport(BaseModel):
    source_name:str=Field(min_length=1,max_length=250)
    content:str=Field(min_length=1,max_length=2_000_000)
class SearchRequest(BaseModel):
    query:str=Field(min_length=1,max_length=1000)
    limit:int=Field(default=5,ge=1,le=20)
class MemoryCreate(BaseModel):
    kind:str=Field(default="semantic",pattern="^(episodic|semantic|procedural|preference)$")
    content:str=Field(min_length=1,max_length=5000)
class GoalCreate(BaseModel):
    title:str=Field(min_length=1,max_length=250)
    description:str=Field(min_length=1,max_length=5000)
class GoalStatusUpdate(BaseModel):
    status:str=Field(pattern="^(open|in_progress|completed|paused)$")

@router.post("/documents/import")
def import_document(req:DocumentImport):
    content=_clean_text(req.source_name,req.content)
    if not content: raise HTTPException(422,"Document has no searchable text.")
    digest=hashlib.sha256(content.encode()).hexdigest()
    con=_connect()
    try:
        existing=con.execute("SELECT id,source_name FROM documents WHERE content_sha256=?",(digest,)).fetchone()
        if existing: return {"id":existing["id"],"source_name":existing["source_name"],"duplicate":True,"chunks":con.execute("SELECT count(*) FROM document_chunks WHERE document_id=?",(existing["id"],)).fetchone()[0],"retrieval":"local keyword search; no embeddings"}
        doc_id=str(uuid.uuid4()); now=datetime.now(timezone.utc).isoformat()
        con.execute("INSERT INTO documents VALUES(?,?,?,?)",(doc_id,req.source_name,digest,now))
        chunks=_chunks(content)
        for i,chunk in enumerate(chunks):
            con.execute("INSERT INTO document_chunks VALUES(?,?,?,?)",(str(uuid.uuid4()),doc_id,i,chunk))
        con.commit()
    finally: con.close()
    _audit("document.imported",{"document_id":doc_id,"source_name":req.source_name,"content_sha256":digest,"chunk_count":len(chunks)})
    return {"id":doc_id,"source_name":req.source_name,"chunks":len(chunks),"duplicate":False,"retrieval":"local keyword search; no embeddings"}
@router.get("/documents")
def list_documents():
    con=_connect()
    try: rows=con.execute("SELECT d.id,d.source_name,d.content_sha256,d.created_at,count(c.id) AS chunks FROM documents d LEFT JOIN document_chunks c ON c.document_id=d.id GROUP BY d.id ORDER BY d.created_at DESC").fetchall()
    finally: con.close()
    return [dict(r) for r in rows]
@router.post("/search")
def search_knowledge(req:SearchRequest):
    terms=[t.lower() for t in re.findall(r"[\\w-]{2,}",req.query)][:12]
    if not terms: return {"query":req.query,"results":[],"method":"keyword"}
    semantic_enabled = settings.semantic_retrieval_enabled and settings.embedding_model_path.expanduser().is_dir()
    clauses=" OR ".join("lower(c.content) LIKE ?" for _ in terms)
    params=[f"%{t}%" for t in terms]
    con=_connect()
    try:
        if semantic_enabled:
            rows=con.execute("""SELECT c.id AS chunk_id,c.chunk_index,c.content,d.id AS document_id,d.source_name
                FROM document_chunks c JOIN documents d ON d.id=c.document_id
                ORDER BY d.created_at DESC LIMIT 5000""").fetchall()
        else:
            rows=con.execute(f"""SELECT c.id AS chunk_id,c.chunk_index,c.content,d.id AS document_id,d.source_name
                FROM document_chunks c JOIN documents d ON d.id=c.document_id
                WHERE {clauses} ORDER BY d.created_at DESC LIMIT ?""",(*params,req.limit*4)).fetchall()
    finally: con.close()
    semantic_scores = _local_semantic_scores(req.query, rows) if semantic_enabled else None
    results=[]
    for row in rows:
        content = row["content"]
        matched=sum(1 for t in terms if t in content.lower())
        lexical = matched / len(terms)
        semantic = semantic_scores.get(str(row["chunk_id"]), 0.0) if semantic_scores is not None else None
        if matched or (semantic is not None and semantic >= 0.25):
            score = (0.45 * lexical + 0.55 * semantic) if semantic is not None else lexical
            results.append({
                "chunk_id":row["chunk_id"],"document_id":row["document_id"],
                "source":row["source_name"],"chunk_index":row["chunk_index"],
                "score":round(score,3),"lexical_score":round(lexical,3),
                **({"semantic_score":round(semantic,3)} if semantic is not None else {}),
                "text":content,
            })
    results.sort(key=lambda x:x["score"],reverse=True)
    method = "local_hybrid" if semantic_scores is not None else "local_keyword"
    note = ("Local embedding similarity blended with lexical overlap; inspect citations."
            if semantic_scores is not None else
            "Keyword retrieval only; confidence scores are lexical overlap, not calibrated probabilities. "
            "If embeddings are enabled but unavailable, check the local model path and optional dependencies.")
    return {"query":req.query,"method":method,"results":results[:req.limit],"note":note}
@router.get("/memory")
def list_memories():
    con=_connect()
    try: rows=con.execute("SELECT id,kind,content,created_at FROM memories ORDER BY created_at DESC").fetchall()
    finally: con.close()
    return [dict(r) for r in rows]
@router.post("/memory")
def create_memory(req:MemoryCreate):
    memory_id=str(uuid.uuid4()); now=datetime.now(timezone.utc).isoformat(); con=_connect()
    try: con.execute("INSERT INTO memories VALUES(?,?,?,?)",(memory_id,req.kind,req.content,now)); con.commit()
    finally: con.close()
    _audit("memory.created",{"memory_id":memory_id,"kind":req.kind,"content_sha256":hashlib.sha256(req.content.encode()).hexdigest()})
    return {"id":memory_id,"kind":req.kind,"created_at":now}
@router.delete("/memory/{memory_id}")
def delete_memory(memory_id:str):
    con=_connect()
    try:
        row=con.execute("SELECT kind FROM memories WHERE id=?",(memory_id,)).fetchone()
        if not row: raise HTTPException(404,"Memory not found.")
        con.execute("DELETE FROM memories WHERE id=?",(memory_id,)); con.commit()
    finally: con.close()
    _audit("memory.deleted",{"memory_id":memory_id,"kind":row["kind"]})
    return {"deleted":True,"id":memory_id}
@router.post("/goals")
def create_goal(req:GoalCreate):
    goal_id=str(uuid.uuid4()); now=datetime.now(timezone.utc).isoformat(); con=_connect()
    try: con.execute("INSERT INTO goals VALUES(?,?,?,?,?)",(goal_id,req.title,req.description,"open",now)); con.commit()
    finally: con.close()
    _audit("goal.created",{"goal_id":goal_id,"title":req.title})
    return {"id":goal_id,"title":req.title,"description":req.description,"status":"open","created_at":now}
@router.get("/goals")
def list_goals():
    con=_connect()
    try: rows=con.execute("SELECT id,title,description,status,created_at FROM goals ORDER BY created_at DESC").fetchall()
    finally: con.close()
    return [dict(r) for r in rows]
@router.post("/goals/{goal_id}/status")
def update_goal_status(goal_id:str, req:GoalStatusUpdate):
    con=_connect()
    try:
        row=con.execute("SELECT status FROM goals WHERE id=?",(goal_id,)).fetchone()
        if not row: raise HTTPException(404,"Goal not found.")
        con.execute("UPDATE goals SET status=? WHERE id=?",(req.status,goal_id))
        con.commit()
    finally: con.close()
    _audit("goal.status_changed",{"goal_id":goal_id,"previous_status":row["status"],"status":req.status})
    return {"id":goal_id,"status":req.status}
