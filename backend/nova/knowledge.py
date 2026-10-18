"""Local text knowledge, memories, goals, and optional offline hybrid retrieval.

Keyword search is the default. Semantic retrieval is opt-in and loads only a local
SentenceTransformers model directory; failures fall back to lexical search.
"""
import hashlib, html, io, json, os, re, shutil, sqlite3, subprocess, tempfile, time, uuid, zipfile
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


def _embedding_model_fingerprint(model_path: Path) -> str:
    """Fingerprint local model files so cached vectors invalidate after model updates."""
    digest = hashlib.sha256()
    root = model_path.resolve()
    digest.update(str(root).encode("utf-8"))
    try:
        for item in sorted(root.rglob("*")):
            if not item.is_file() or item.is_symlink():
                continue
            try:
                stat = item.stat()
                relative = item.relative_to(root).as_posix()
                digest.update(f"{relative}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode("utf-8"))
            except OSError:
                continue
    except OSError:
        return hashlib.sha256(str(root).encode("utf-8")).hexdigest()
    return digest.hexdigest()


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
        fingerprint = _embedding_model_fingerprint(model_path)
        if _embedding_model is None or _embedding_model_path != path:
            _embedding_model = SentenceTransformer(
                path, device="cpu", local_files_only=True, trust_remote_code=False
            )
            _embedding_model_path = path
        texts = [str(row["content"]) for row in rows]
        if not texts:
            return {}
        con = _connect()
        try:
            con.execute("""CREATE TABLE IF NOT EXISTS chunk_embeddings (
                chunk_id TEXT NOT NULL,
                model_fingerprint TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                dimension INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(chunk_id, model_fingerprint)
            )""")
            cached = {}
            missing = []
            for row, content in zip(rows, texts):
                chunk_id = str(row["chunk_id"])
                content_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                stored = con.execute(
                    "SELECT content_sha256, vector_json, dimension FROM chunk_embeddings "
                    "WHERE chunk_id=? AND model_fingerprint=?",
                    (chunk_id, fingerprint),
                ).fetchone()
                vector = None
                if stored and stored["content_sha256"] == content_digest:
                    try:
                        candidate = np.asarray(json.loads(stored["vector_json"]), dtype=np.float32)
                        if candidate.ndim == 1 and len(candidate) == int(stored["dimension"]) and np.isfinite(candidate).all():
                            vector = candidate
                    except (ValueError, TypeError, json.JSONDecodeError):
                        vector = None
                if vector is None:
                    missing.append((chunk_id, content, content_digest))
                else:
                    cached[chunk_id] = vector
            if missing:
                encoded = np.asarray(_embedding_model.encode(
                    [item[1] for item in missing], normalize_embeddings=True,
                    convert_to_numpy=True, show_progress_bar=False,
                ), dtype=np.float32)
                if encoded.ndim != 2 or encoded.shape[0] != len(missing) or not np.isfinite(encoded).all():
                    raise ValueError("Embedding model returned invalid vectors")
                now = datetime.now(timezone.utc).isoformat()
                for item, vector in zip(missing, encoded):
                    vector = np.asarray(vector, dtype=np.float32)
                    con.execute(
                        "INSERT OR REPLACE INTO chunk_embeddings "
                        "(chunk_id,model_fingerprint,content_sha256,vector_json,dimension,created_at) "
                        "VALUES(?,?,?,?,?,?)",
                        (item[0], fingerprint, item[2], json.dumps(vector.tolist(), separators=(",", ":")),
                         int(vector.size), now),
                    )
                    cached[item[0]] = vector
                con.commit()
                _audit("knowledge.embedding_cache_updated", {
                    "model_fingerprint": fingerprint, "vectors_added": len(missing),
                    "dimensions": int(encoded.shape[1]) if encoded.size else 0,
                })
        finally:
            con.close()
        query_vector = np.asarray(_embedding_model.encode(
            [query], normalize_embeddings=True, convert_to_numpy=True,
            show_progress_bar=False,
        )[0], dtype=np.float32)
        if query_vector.ndim != 1 or not np.isfinite(query_vector).all():
            raise ValueError("Embedding model returned an invalid query vector")
        vectors = np.vstack([cached[str(row["chunk_id"])] for row in rows])
        if vectors.shape[1] != query_vector.shape[0]:
            raise ValueError("Cached embedding dimensions do not match the query model")
        scores = vectors @ query_vector
        return {str(row["chunk_id"]): max(0.0, min(1.0, float(score)))
                for row, score in zip(rows, scores)}
    except (ImportError, OSError, ValueError, RuntimeError, TypeError, sqlite3.Error):
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



def _resolve_pdf_ocr_binary(configured: str, candidates: tuple[str, ...]) -> str | None:
    if configured.strip():
        path = Path(configured).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
        return None
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return str(Path(found).resolve())
    return None


def _ocr_scanned_pdf(filename: str, data: bytes) -> str:
    """OCR a bounded PDF with explicitly enabled local Poppler and Tesseract."""
    if not settings.pdf_ocr_enabled:
        raise HTTPException(422, "Scanned-PDF OCR is disabled; set NOVA_PDF_OCR_ENABLED=true to enable it.")
    renderer = _resolve_pdf_ocr_binary(settings.pdf_renderer_cli_path, ("pdftoppm",))
    tesseract = _resolve_pdf_ocr_binary(settings.tesseract_cli_path, ("tesseract",))
    if not renderer or not tesseract:
        raise HTTPException(503, "Scanned-PDF OCR requires local pdftoppm and Tesseract binaries.")
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise HTTPException(503, "Scanned-PDF OCR requires the optional local pypdf dependency.") from exc
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise HTTPException(422, "Encrypted PDFs are not supported for OCR.")
        page_count = len(reader.pages)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, "PDF could not be validated before OCR.") from exc
    if page_count < 1:
        raise HTTPException(422, "PDF has no pages to OCR.")
    if page_count > settings.pdf_ocr_max_pages:
        raise HTTPException(413, f"Scanned-PDF OCR is limited to {settings.pdf_ocr_max_pages} pages.")

    workspace = settings.workspace.resolve()
    ocr_root = workspace / ".nova-ocr"
    if ocr_root.is_symlink():
        raise HTTPException(403, "OCR work directory must not be a symbolic link.")
    ocr_root.mkdir(parents=True, exist_ok=True)
    if workspace not in ocr_root.resolve().parents:
        raise HTTPException(403, "OCR work directory must remain inside the NOVA workspace.")

    deadline = time.monotonic() + settings.pdf_ocr_timeout_seconds
    parts: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="pdf-ocr-", dir=ocr_root) as temporary:
            temp_dir = Path(temporary)
            pdf_path = temp_dir / "input.pdf"
            with pdf_path.open("xb") as stream:
                stream.write(data)
            for page in range(1, page_count + 1):
                remaining = int(deadline - time.monotonic())
                if remaining <= 0:
                    raise HTTPException(504, "Scanned-PDF OCR exceeded its total time budget.")
                prefix = temp_dir / f"page-{page}"
                try:
                    rendered = subprocess.run(
                        [renderer, "-f", str(page), "-l", str(page), "-png",
                         "-singlefile", "-scale-to", "2000", str(pdf_path), str(prefix)],
                        shell=False, capture_output=True, text=True, timeout=remaining,
                        check=False, cwd=str(temp_dir),
                    )
                except subprocess.TimeoutExpired as exc:
                    raise HTTPException(504, "PDF page rendering timed out.") from exc
                image_path = Path(str(prefix) + ".png")
                if rendered.returncode != 0 or not image_path.is_file():
                    raise HTTPException(502, "Local Poppler failed to render a PDF page.")
                if image_path.stat().st_size > 20_000_000:
                    raise HTTPException(413, "Rendered PDF page exceeds the 20 MB OCR safety limit.")
                remaining = int(deadline - time.monotonic())
                if remaining <= 0:
                    raise HTTPException(504, "Scanned-PDF OCR exceeded its total time budget.")
                try:
                    recognized = subprocess.run(
                        [tesseract, str(image_path), "stdout", "--psm", "6"],
                        shell=False, capture_output=True, text=True, timeout=remaining,
                        check=False, cwd=str(temp_dir),
                    )
                except subprocess.TimeoutExpired as exc:
                    raise HTTPException(504, "Tesseract OCR timed out.") from exc
                if recognized.returncode != 0:
                    raise HTTPException(502, "Local Tesseract OCR failed on a rendered page.")
                parts.append((recognized.stdout or "").strip())
                if sum(map(len, parts)) > MAX_EXTRACTED_TEXT_CHARS:
                    raise HTTPException(413, "OCR output exceeds the 2 MB extracted-text limit.")
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(500, "Unable to safely stage local PDF OCR files.") from exc
    return re.sub(r"\s+", " ", "\n".join(parts)).strip()


@router.post("/documents/import-file")
async def import_document_file(file: UploadFile = File(...)):
    filename = Path(file.filename or "upload").name
    if not filename or filename in {".", ".."}:
        raise HTTPException(422, "A valid local filename is required.")
    data = await file.read(MAX_DOCUMENT_UPLOAD_BYTES + 1)
    if len(data) > MAX_DOCUMENT_UPLOAD_BYTES:
        raise HTTPException(413, "Upload exceeds the 20 MB limit.")
    extracted = extract_document_text(filename, data)
    extraction = "local text extraction"
    if not extracted and Path(filename).suffix.lower() == ".pdf" and settings.pdf_ocr_enabled:
        extracted = _ocr_scanned_pdf(filename, data)
        extraction = "local Poppler rendering + Tesseract OCR"
    if not extracted:
        raise HTTPException(422, "Document contains no extractable text. For scanned PDFs, enable local PDF OCR and install Poppler + Tesseract.")
    result = import_document(DocumentImport(source_name=filename, content=extracted))
    _audit("document.file_extracted", {
        "document_id": result["id"], "source_name": filename,
        "file_sha256": hashlib.sha256(data).hexdigest(), "extracted_chars": len(extracted),
        "extraction": extraction,
    })
    return {**result, "extracted_chars": len(extracted), "extraction": extraction}

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
    terms=[t.lower() for t in re.findall(r"[\w-]{2,}",req.query)][:12]
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

class CitationReference(BaseModel):
    chunk_id: str = Field(min_length=1, max_length=80)
    quote: str = Field(min_length=1, max_length=1000)


class CitationVerificationRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    citations: list[CitationReference] = Field(min_length=1, max_length=20)


@router.post("/citations/verify")
def verify_citations(req: CitationVerificationRequest):
    """Verify citation identity and exact source quotes; this does not prove claim entailment."""
    con = _connect()
    try:
        verified = []
        for citation in req.citations:
            row = con.execute(
                "SELECT c.id AS chunk_id,c.chunk_index,c.content,d.id AS document_id,d.source_name "
                "FROM document_chunks c JOIN documents d ON d.id=c.document_id WHERE c.id=?",
                (citation.chunk_id,),
            ).fetchone()
            if row is None:
                verified.append({
                    "chunk_id": citation.chunk_id, "source_exists": False,
                    "quote_verified": False, "grounded": False,
                    "reason": "Unknown chunk ID; it does not reference an imported local source.",
                })
                continue
            normalize = lambda value: re.sub(r"\\s+", " ", value).strip()
            quote_verified = normalize(citation.quote) in normalize(row["content"])
            verified.append({
                "chunk_id": row["chunk_id"], "document_id": row["document_id"],
                "source": row["source_name"], "chunk_index": row["chunk_index"],
                "source_exists": True, "quote_verified": quote_verified,
                "grounded": quote_verified,
                "reason": ("Exact quote found in the imported source chunk."
                           if quote_verified else "Quoted text does not exactly match this source chunk."),
            })
    finally:
        con.close()
    result = {
        "query": req.query,
        "verified": verified,
        "all_grounded": all(item["grounded"] for item in verified),
        "verification_scope": "Source identity and exact quote only; semantic entailment is not verified.",
    }
    _audit("citations.verified", {
        "citation_count": len(verified),
        "grounded_count": sum(1 for item in verified if item["grounded"]),
        "unknown_source_count": sum(1 for item in verified if not item["source_exists"]),
    })
    return result


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
