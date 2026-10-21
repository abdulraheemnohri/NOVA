"""Local configuration registry for MCP servers, online tools and API providers."""
from __future__ import annotations
import json,re,sqlite3,uuid
from datetime import datetime,timezone
from urllib.parse import urlparse
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from nova.config import settings
from nova.audit import append_audit
router=APIRouter(prefix="/api/integrations",tags=["integrations"])
ENV=re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
MCP_CATALOG=[
{"id":"filesystem","name":"Filesystem","category":"Local files","transport":"stdio","package":"@modelcontextprotocol/server-filesystem","free":True,"offline":True,"description":"Restrict access to explicitly approved directories."},
{"id":"git","name":"Git","category":"Developer","transport":"stdio","package":"mcp-server-git","free":True,"offline":True,"description":"Inspect a specific repository; review write access."},
{"id":"memory","name":"Memory","category":"Knowledge","transport":"stdio","package":"@modelcontextprotocol/server-memory","free":True,"offline":True,"description":"Local graph memory server."},
{"id":"fetch","name":"Fetch","category":"Web","transport":"stdio","package":"mcp-server-fetch","free":True,"offline":False,"description":"Fetch public web pages; requires network."},
{"id":"playwright","name":"Playwright","category":"Browser","transport":"stdio","package":"@playwright/mcp","free":True,"offline":False,"description":"Browser automation; requires network/browser permissions."},
{"id":"sqlite","name":"SQLite","category":"Databases","transport":"stdio","package":"mcp-server-sqlite","free":True,"offline":True,"description":"Local SQLite access; prefer read-only databases."},
{"id":"sequential-thinking","name":"Sequential Thinking","category":"Reasoning","transport":"stdio","package":"@modelcontextprotocol/server-sequential-thinking","free":True,"offline":True,"description":"Local structured reasoning helper."},
{"id":"everything","name":"Everything","category":"Testing","transport":"stdio","package":"@modelcontextprotocol/server-everything","free":True,"offline":True,"description":"MCP protocol test server, not production integration."},
]
ONLINE_CATALOG=[
{"id":"google-search","name":"Google Web Search","category":"Search","free":True,"url":"https://www.google.com/search","description":"NOVA's existing Google search adapter; online."},
{"id":"duckduckgo-search","name":"DuckDuckGo Search","category":"Search","free":True,"url":"https://duckduckgo.com/","description":"NOVA's existing DuckDuckGo adapter; online."},
{"id":"duck-ai","name":"Duck.ai","category":"AI website","free":True,"url":"https://duck.ai/","description":"External website, not a native API integration."},
{"id":"huggingface","name":"Hugging Face Hub","category":"Models","free":True,"url":"https://huggingface.co/","description":"Public model catalogue; downloads consume disk space."},
{"id":"github","name":"GitHub","category":"Developer","free":True,"url":"https://github.com/","description":"Public repository browsing; API limits/authentication may apply."},
]
def _db():
 settings.database_path.parent.mkdir(parents=True,exist_ok=True)
 c=sqlite3.connect(settings.database_path,timeout=10);c.row_factory=sqlite3.Row
 c.execute("""CREATE TABLE IF NOT EXISTS integration_configs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,name TEXT NOT NULL,config_json TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""");c.commit();return c
def _now(): return datetime.now(timezone.utc).isoformat()
def _pub(row):
 d=dict(row);d["config"]=json.loads(d.pop("config_json"));d["enabled"]=bool(d["enabled"]);return d
def _list(kind):
 c=_db()
 try:return [_pub(r) for r in c.execute("SELECT * FROM integration_configs WHERE kind=? ORDER BY updated_at DESC",(kind,))]
 finally:c.close()
def _validate(kind,cfg):
 if not isinstance(cfg,dict):raise HTTPException(422,"Configuration must be an object.")
 if kind=="mcp":
  t=cfg.get("transport","streamable_http")
  if t not in {"stdio","streamable_http"}:raise HTTPException(422,"Unsupported MCP transport.")
  if t=="streamable_http":
   p=urlparse(cfg.get("endpoint",""))
   if p.scheme not in {"https","http"} or not p.hostname or p.username or p.password or p.fragment:raise HTTPException(422,"MCP endpoint must be an absolute HTTP(S) URL without embedded credentials.")
   if p.scheme=="http" and p.hostname not in {"127.0.0.1","localhost","::1"}:raise HTTPException(422,"Remote MCP endpoints must use HTTPS.")
  else:
   if not isinstance(cfg.get("command"),str) or not cfg["command"].strip() or len(cfg["command"])>300:raise HTTPException(422,"stdio MCP requires an explicit command.")
   args=cfg.get("args",[])
   if not isinstance(args,list) or len(args)>40 or any(not isinstance(x,str) or len(x)>500 for x in args):raise HTTPException(422,"Invalid stdio arguments.")
  refs=cfg.get("env_refs",{})
  if not isinstance(refs,dict) or len(refs)>40:raise HTTPException(422,"Invalid environment references.")
  for k,v in refs.items():
   if not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,63}",k) or (v is not None and (not isinstance(v,str) or not ENV.fullmatch(v))):raise HTTPException(422,"Use environment-variable names for credentials; never store secret values here.")
 elif kind=="api":
  u=cfg.get("base_url","")
  if u:
   p=urlparse(u)
   if p.scheme not in {"https","http"} or not p.hostname or p.username or p.password or p.fragment:raise HTTPException(422,"API base URL must be absolute HTTP(S).")
   if p.scheme=="http" and p.hostname not in {"127.0.0.1","localhost","::1"}:raise HTTPException(422,"Remote API endpoints must use HTTPS.")
  v=cfg.get("api_key_env")
  if v is not None and (not isinstance(v,str) or not ENV.fullmatch(v)):raise HTTPException(422,"Use an environment-variable name, not a secret.")
  if cfg.get("auth_type","none") not in {"none","bearer_env","header_env","oauth_external"}:raise HTTPException(422,"Unsupported authentication mode.")
 elif kind=="online_tool":
  if cfg.get("category","Other") not in {"Search","AI website","Models","Research","Developer","Other"}:raise HTTPException(422,"Invalid category.")
  p=urlparse(cfg.get("url",""))
  if p.scheme!="https" or not p.hostname or p.username or p.password:raise HTTPException(422,"Online tool links must use HTTPS.")
class Create(BaseModel):
 model_config=ConfigDict(extra="forbid")
 name:str=Field(min_length=1,max_length=100);config:dict=Field(default_factory=dict);enabled:bool=False
class Update(BaseModel):
 model_config=ConfigDict(extra="forbid")
 name:str|None=Field(default=None,min_length=1,max_length=100);config:dict|None=None;enabled:bool|None=None
@router.get("/catalog")
def catalog():return {"mcp_servers":MCP_CATALOG,"online_tools":ONLINE_CATALOG,"notes":["Catalogue entries are templates, not installed/connected servers.","Free/open source does not guarantee free hosted APIs or unlimited usage; check licence, terms and limits."]}
def _create(kind,r):
 _validate(kind,r.config);i=str(uuid.uuid4());n=_now();c=_db()
 try:
  c.execute("INSERT INTO integration_configs VALUES(?,?,?,?,?,?,?)",(i,kind,r.name.strip(),json.dumps(r.config),int(r.enabled),n,n));c.commit();row=c.execute("SELECT * FROM integration_configs WHERE id=?",(i,)).fetchone()
 finally:c.close()
 append_audit(settings.audit_path,"integration.created",{"kind":kind,"id":i,"enabled":r.enabled});return _pub(row)
def _update(kind,i,r):
 c=_db()
 try:
  old=c.execute("SELECT * FROM integration_configs WHERE id=? AND kind=?",(i,kind)).fetchone()
  if old is None:raise HTTPException(404,"Integration not found.")
  name=r.name.strip() if r.name is not None else old["name"];cfg=r.config if r.config is not None else json.loads(old["config_json"]);_validate(kind,cfg)
  enabled=int(r.enabled) if r.enabled is not None else old["enabled"]
  c.execute("UPDATE integration_configs SET name=?,config_json=?,enabled=?,updated_at=? WHERE id=?",(name,json.dumps(cfg),enabled,_now(),i));c.commit();row=c.execute("SELECT * FROM integration_configs WHERE id=?",(i,)).fetchone()
 finally:c.close()
 append_audit(settings.audit_path,"integration.updated",{"kind":kind,"id":i,"enabled":bool(enabled)});return _pub(row)
def _delete(kind,i):
 c=_db()
 try:
  cur=c.execute("DELETE FROM integration_configs WHERE id=? AND kind=?",(i,kind));c.commit()
  if not cur.rowcount:raise HTTPException(404,"Integration not found.")
 finally:c.close()
 append_audit(settings.audit_path,"integration.deleted",{"kind":kind,"id":i});return {"deleted":True,"id":i}
for _kind,_route in (("mcp","mcp"),("api","apis"),("online_tool","online-tools")):
 def _install(kind,route):
  @router.get("/"+route)
  def get_items():return {"items":_list(kind)}
  @router.post("/"+route,status_code=201)
  def create_item(req:Create):return _create(kind,req)
  @router.patch("/"+route+"/{item_id}")
  def update_item(item_id:str,req:Update):return _update(kind,item_id,req)
  @router.delete("/"+route+"/{item_id}")
  def delete_item(item_id:str):return _delete(kind,item_id)
 _install(_kind,_route)
