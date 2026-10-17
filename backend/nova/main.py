from __future__ import annotations
import hashlib, json, sqlite3, uuid
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from nova.audit import append_audit, verify_audit
from nova.config import settings
from nova.litert import LiteRTError, chat, health
from nova.policy import evaluate_tool
from nova.knowledge import router as knowledge_router, initialize_knowledge

app=FastAPI(title="NOVA — Neural Offline Verified Agent",version="0.1.0")
app.include_router(knowledge_router)
app.add_middleware(CORSMiddleware,allow_origins=["http://127.0.0.1:5173","http://localhost:5173","http://127.0.0.1:4173"],allow_credentials=False,allow_methods=["GET","POST"],allow_headers=["Content-Type"])
class ChatRequest(BaseModel):
    message: str=Field(min_length=1,max_length=20000)
    max_tokens: int=Field(default=512,ge=1,le=4096)
class ApprovalRequest(BaseModel):
    action: str=Field(min_length=1,max_length=80)
    payload: dict[str,Any]=Field(default_factory=dict)
    reason: str=Field(min_length=1,max_length=1000)
class FileWriteRequest(BaseModel):
    relative_path: str=Field(min_length=1,max_length=500)
    content: str=Field(max_length=1000000)
    approval_id: str|None=None

def _db():
    settings.database_path.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(settings.database_path); con.row_factory=sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY, action TEXT NOT NULL,
      payload_json TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, decided_at TEXT)""")
    con.commit(); return con
def _audit(event:str, details:dict[str,Any]): append_audit(settings.audit_path,event,details)
def _safe_path(relative:str)->Path:
    root=settings.workspace.resolve(); target=(root/relative).resolve()
    if target==root or root not in target.parents: raise HTTPException(403,"Path escapes workspace.")
    return target
@app.on_event("startup")
def startup():
    settings.workspace.mkdir(parents=True,exist_ok=True)
    con=_db(); con.close()
    initialize_knowledge()
@app.get("/api/health")
def api_health():
    valid,count=verify_audit(settings.audit_path)
    return {"status":"ok","offline_mode":True,"llm_runtime":"LiteRT-LM only","litert":health(),"audit_chain_valid":valid,"audit_event_count":count}
@app.post("/api/chat")
def api_chat(req:ChatRequest):
    _audit("chat.request",{"message_sha256":hashlib.sha256(req.message.encode()).hexdigest()})
    try: answer=chat(req.message,req.max_tokens)
    except LiteRTError as exc:
        _audit("chat.failure",{"error":str(exc)}); raise HTTPException(503,str(exc)) from exc
    _audit("chat.response",{"answer_sha256":hashlib.sha256(answer.encode()).hexdigest()})
    return {"answer":answer,"model":settings.litert_model,"runtime":"LiteRT-LM"}
@app.get("/api/approvals")
def list_approvals():
    con=_db()
    try: rows=con.execute("SELECT * FROM approvals ORDER BY created_at DESC").fetchall()
    finally: con.close()
    return [dict(r) for r in rows]
@app.post("/api/approvals")
def create_approval(req:ApprovalRequest):
    policy=evaluate_tool(req.action)
    if not policy.requires_approval:
        _audit("approval.blocked",{"action":req.action,"reason":policy.reason})
        raise HTTPException(403,policy.reason)
    aid=str(uuid.uuid4()); con=_db()
    try:
        con.execute("INSERT INTO approvals(id,action,payload_json,reason,status) VALUES(?,?,?,?, 'pending')",(aid,req.action,json.dumps(req.payload,sort_keys=True),req.reason)); con.commit()
    finally: con.close()
    _audit("approval.requested",{"approval_id":aid,"action":req.action,"payload_sha256":hashlib.sha256(json.dumps(req.payload,sort_keys=True).encode()).hexdigest()})
    return {"id":aid,"status":"pending","message":"Approval recorded; no action has run."}
@app.post("/api/approvals/{approval_id}/decision")
def decide(approval_id:str,decision:str):
    if decision not in {"approve","reject"}: raise HTTPException(422,"Decision must be approve or reject.")
    con=_db()
    try:
        row=con.execute("SELECT status,action FROM approvals WHERE id=?",(approval_id,)).fetchone()
        if row is None: raise HTTPException(404,"Approval not found.")
        if row["status"]!="pending": raise HTTPException(409,"Approval already decided.")
        status="approved" if decision=="approve" else "rejected"
        con.execute("UPDATE approvals SET status=?,decided_at=CURRENT_TIMESTAMP WHERE id=?",(status,approval_id)); con.commit()
    finally: con.close()
    _audit("approval.decision",{"approval_id":approval_id,"decision":decision,"action":row["action"]})
    return {"id":approval_id,"status":status}
@app.post("/api/workspace/write")
def write_file(req:FileWriteRequest):
    target=_safe_path(req.relative_path); content_hash=hashlib.sha256(req.content.encode()).hexdigest(); approved=False
    if req.approval_id:
        con=_db()
        try: row=con.execute("SELECT action,payload_json,status FROM approvals WHERE id=?",(req.approval_id,)).fetchone()
        finally: con.close()
        if row and row["status"]=="approved" and row["action"]=="workspace_write":
            try: payload=json.loads(row["payload_json"])
            except json.JSONDecodeError: payload={}
            approved=(payload.get("relative_path")==req.relative_path and payload.get("content_sha256")==content_hash)
    policy=evaluate_tool("workspace_write",approved)
    if not policy.allowed:
        _audit("workspace.write.blocked",{"path":req.relative_path,"reason":policy.reason})
        raise HTTPException(403,policy.reason)
    target.parent.mkdir(parents=True,exist_ok=True); previous=target.read_bytes() if target.exists() else None
    snapshot=None
    if previous is not None:
        snapdir=settings.workspace/".nova-snapshots"; snapdir.mkdir(parents=True,exist_ok=True)
        snapshot=snapdir/(hashlib.sha256(str(target).encode()).hexdigest()+".bak"); snapshot.write_bytes(previous)
    target.write_text(req.content,encoding="utf-8")
    _audit("workspace.write",{"path":req.relative_path,"content_sha256":content_hash,"snapshot":str(snapshot.relative_to(settings.workspace)) if snapshot else None,"approval_id":req.approval_id})
    return {"written":True,"path":req.relative_path,"snapshot_created":snapshot is not None}
@app.get("/api/audit/verify")
def audit_status():
    valid,count=verify_audit(settings.audit_path); return {"valid":valid,"events_verified":count}
@app.get("/api/settings")
def get_settings():
    return {"mode":"offline","llm_runtime":"LiteRT-LM only","litert_base_url":settings.litert_base_url,"model_id":settings.litert_model,"require_approval_for_writes":settings.require_approval_for_writes,"network_policy":"loopback-only","tool_policy":"default-deny"}
