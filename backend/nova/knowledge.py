"""Local text knowledge, memories, and goal records.

Retrieval is deterministic local keyword search in this phase; it does not claim
semantic/vector retrieval until a verified local embedding adapter is implemented.
"""
import hashlib, html, json, re, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from nova.config import settings
from nova.audit import append_audit

router=APIRouter(prefix="/api")
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
    if suffix not in {".txt",".md",".markdown",".csv",".json",".html",".htm"}:
        raise HTTPException(415,"This phase supports TXT, Markdown, CSV, JSON, and HTML text only.")
    if suffix in {".html",".htm"}:
        content=re.sub(r"(?is)<(script|style).*?>.*?</\\1>"," ",content)
        content=re.sub(r"(?s)<[^>]+>"," ",content)
        content=html.unescape(content)
    return re.sub(r"\\s+"," ",content).strip()
def _chunks(text:str, size:int=1200, overlap:int=150)->list[str]:
    if not text: return []
    result=[]; start=0
    while start<len(text):
        end=min(len(text),start+size); result.append(text[start:end])
        if end==len(text): break
        start=end-overlap
    return result
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

@router.post("/documents/import")
def import_document(req:DocumentImport):
    content=_clean_text(req.source_name,req.content)
    if not content: raise HTTPException(422,"Document has no searchable text.")
    digest=hashlib.sha256(content.encode()).hexdigest()
    con=_connect()
    try:
        existing=con.execute("SELECT id FROM documents WHERE content_sha256=?",(digest,)).fetchone()
        if existing: return {"id":existing["id"],"duplicate":True,"chunks":con.execute("SELECT count(*) FROM document_chunks WHERE document_id=?",(existing["id"],)).fetchone()[0]}
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
    clauses=" OR ".join("lower(c.content) LIKE ?" for _ in terms)
    params=[f"%{t}%" for t in terms]
    con=_connect()
    try:
        rows=con.execute(f"""SELECT c.id AS chunk_id,c.chunk_index,c.content,d.id AS document_id,d.source_name
        FROM document_chunks c JOIN documents d ON d.id=c.document_id WHERE {clauses} ORDER BY d.created_at DESC LIMIT ?""",(*params,req.limit*4)).fetchall()
    finally: con.close()
    results=[]
    for row in rows:
        matched=sum(1 for t in terms if t in row["content"].lower())
        if matched:
            results.append({"chunk_id":row["chunk_id"],"document_id":row["document_id"],"source":row["source_name"],"chunk_index":row["chunk_index"],"score":round(matched/len(terms),3),"text":row["content"]})
    results.sort(key=lambda x:x["score"],reverse=True)
    return {"query":req.query,"method":"local_keyword","results":results[:req.limit],"note":"Keyword retrieval only; confidence scores are lexical overlap, not calibrated probabilities."}
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
