"""Secure opt-in WhatsApp Cloud API bridge for up to five external agents."""
import hashlib,hmac,ipaddress,json,os,re,socket,sqlite3,urllib.error,urllib.request,uuid
from datetime import datetime,timezone
from urllib.parse import urlparse
from fastapi import APIRouter,HTTPException,Request,Response
from pydantic import BaseModel,ConfigDict,Field
from nova.config import settings
from nova.audit import append_audit
router=APIRouter(prefix="/api/whatsapp",tags=["WhatsApp"])
NOTICE="Messages are processed by Meta and the configured third-party agent service. WhatsApp does not consider these chats end-to-end encrypted. Only allowlisted senders are forwarded; do not send passwords or sensitive data."
def env(k):return os.environ.get(k,"").strip()
def db():
 settings.database_path.parent.mkdir(parents=True,exist_ok=True);c=sqlite3.connect(settings.database_path,timeout=10);c.row_factory=sqlite3.Row
 c.execute("CREATE TABLE IF NOT EXISTS whatsapp_agents(id TEXT PRIMARY KEY,slug TEXT UNIQUE,name TEXT,endpoint TEXT,token_env_key TEXT,enabled INTEGER,created_at TEXT)")
 c.execute("CREATE TABLE IF NOT EXISTS whatsapp_events(message_id TEXT PRIMARY KEY,status TEXT,received_at TEXT)");c.commit();return c
def agents():
 c=db()
 try:return [dict(r)|{"enabled":bool(r["enabled"])} for r in c.execute("SELECT * FROM whatsapp_agents ORDER BY created_at").fetchall()]
 finally:c.close()
def endpoint(url):
 u=urlparse(url)
 if u.scheme!="https" or not u.hostname or u.username or u.password or u.port not in (None,443):raise ValueError("Agent URL must be HTTPS on port 443, without embedded credentials.")
 host=u.hostname.lower()
 if host=="localhost" or host.endswith((".local",".localhost",".internal")):raise ValueError("Private hostnames are not allowed.")
 try:
  ip=ipaddress.ip_address(host)
  if not ip.is_global:raise ValueError("Private IP endpoints are forbidden.")
 except ValueError as e:
  if "forbidden" in str(e):raise
 return u
def public_dns(host):
 try:ips={x[4][0] for x in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)}
 except OSError as e:raise RuntimeError("Agent DNS lookup failed.") from e
 if not ips or any(not ipaddress.ip_address(x).is_global for x in ips):raise RuntimeError("Agent endpoint resolves to a private IP.")
def post(url,data,headers,timeout=20):
 req=urllib.request.Request(url,data=json.dumps(data).encode(),headers={"Content-Type":"application/json","User-Agent":"NOVA-WhatsApp",**headers},method="POST")
 class NoRedirect(urllib.request.HTTPRedirectHandler):
  def redirect_request(self,*a,**k):return None
 try:
  with urllib.request.build_opener(NoRedirect).open(req,timeout=timeout) as r:out=json.loads(r.read(1000000))
 except (urllib.error.URLError,TimeoutError,OSError,json.JSONDecodeError) as e:raise RuntimeError("Remote endpoint request failed.") from e
 if not isinstance(out,dict):raise RuntimeError("Remote endpoint returned invalid JSON.")
 return out
class NewAgent(BaseModel):
 model_config=ConfigDict(extra="forbid")
 name:str=Field(min_length=1,max_length=80);endpoint:str=Field(min_length=10,max_length=500);token_env_key:str=Field(pattern=r"^NOVA_WHATSAPP_AGENT_[A-Z0-9_]{1,40}_TOKEN$");enabled:bool=False
class Toggle(BaseModel):
 model_config=ConfigDict(extra="forbid")
 enabled:bool
@router.get("/status")
def status():
 return {"configured":all(env(x) for x in ["NOVA_WHATSAPP_VERIFY_TOKEN","NOVA_WHATSAPP_APP_SECRET","NOVA_WHATSAPP_ACCESS_TOKEN","NOVA_WHATSAPP_PHONE_NUMBER_ID"]),"allowlisted_senders":len([x for x in env("NOVA_WHATSAPP_ALLOWED_SENDERS").split(",") if x.strip()]),"agents":agents(),"max_agents":5,"privacy_notice":NOTICE,"setup_env":["NOVA_WHATSAPP_VERIFY_TOKEN","NOVA_WHATSAPP_APP_SECRET","NOVA_WHATSAPP_ACCESS_TOKEN","NOVA_WHATSAPP_PHONE_NUMBER_ID","NOVA_WHATSAPP_ALLOWED_SENDERS"]}
@router.get("/agents")
def get_agents():return agents()
@router.post("/agents",status_code=201)
def add_agent(req:NewAgent):
 try:u=endpoint(req.endpoint)
 except ValueError as e:raise HTTPException(422,str(e)) from e
 old=agents()
 if len(old)>=5:raise HTTPException(409,"Maximum five agents.")
 if any(a["token_env_key"]==req.token_env_key for a in old):raise HTTPException(409,"Use a unique token environment variable per agent.")
 slug=re.sub(r"[^a-z0-9]+","-",req.name.lower()).strip("-")[:32] or "agent";aid=str(uuid.uuid4())
 if any(a["slug"]==slug for a in old):slug+="-"+aid[:6]
 c=db()
 try:c.execute("INSERT INTO whatsapp_agents VALUES(?,?,?,?,?,?,?)",(aid,slug,req.name.strip(),u.geturl(),req.token_env_key,int(req.enabled),datetime.now(timezone.utc).isoformat()));c.commit()
 finally:c.close()
 append_audit(settings.audit_path,"whatsapp.agent.created",{"agent_id":aid,"enabled":req.enabled});return next(a for a in agents() if a["id"]==aid)
@router.put("/agents/{aid}")
def toggle_agent(aid:str,req:Toggle):
 c=db()
 try:
  cur=c.execute("UPDATE whatsapp_agents SET enabled=? WHERE id=?",(int(req.enabled),aid));c.commit()
  if not cur.rowcount:raise HTTPException(404,"Agent not found.")
 finally:c.close()
 return {"id":aid,"enabled":req.enabled}
@router.delete("/agents/{aid}")
def remove_agent(aid:str):
 c=db()
 try:
  cur=c.execute("DELETE FROM whatsapp_agents WHERE id=?",(aid,));c.commit()
  if not cur.rowcount:raise HTTPException(404,"Agent not found.")
 finally:c.close()
 return {"deleted":True}
@router.get("/webhook")
def verify(request:Request):
 if request.query_params.get("hub.mode")=="subscribe" and env("NOVA_WHATSAPP_VERIFY_TOKEN") and hmac.compare_digest(request.query_params.get("hub.verify_token",""),env("NOVA_WHATSAPP_VERIFY_TOKEN")):return Response(request.query_params.get("hub.challenge",""),media_type="text/plain")
 raise HTTPException(403,"Webhook verification failed.")
def send(to,text):
 ver=env("NOVA_WHATSAPP_GRAPH_API_VERSION") or "v23.0";phone=env("NOVA_WHATSAPP_PHONE_NUMBER_ID");token=env("NOVA_WHATSAPP_ACCESS_TOKEN")
 if not phone or not token:raise RuntimeError("WhatsApp Cloud API credentials missing.")
 post(f"https://graph.facebook.com/{ver}/{phone}/messages",{"messaging_product":"whatsapp","to":to,"type":"text","text":{"body":text[:4000]}},{"Authorization":"Bearer "+token})
def dispatch(sender,text,mid):
 allow={x.strip().lstrip("+") for x in env("NOVA_WHATSAPP_ALLOWED_SENDERS").split(",") if x.strip()}
 if sender not in allow:append_audit(settings.audit_path,"whatsapp.blocked",{"sender_sha256":hashlib.sha256(sender.encode()).hexdigest()});return
 enabled=[a for a in agents() if a["enabled"]];m=re.match(r"^/agent\s+([a-z0-9-]+)\s+([\s\S]+)$",text.strip(),re.I)
 if m:agent=next((a for a in enabled if a["slug"]==m.group(1).lower()),None);body=m.group(2).strip()
 elif len(enabled)==1:agent=enabled[0];body=text
 else:send(sender,"Choose an agent: "+(", ".join("/agent "+a["slug"] for a in enabled) or "no agents enabled"));return
 if not agent:send(sender,"Unknown or disabled agent. Check the /agent name and try again.");return
 u=endpoint(agent["endpoint"]);public_dns(u.hostname);secret=env(agent["token_env_key"])
 if not secret:raise RuntimeError("Agent token environment variable is missing.")
 answer=post(u.geturl(),{"message":body,"channel":"whatsapp","sender":sender,"agent":agent["slug"],"message_id":mid},{"Authorization":"Bearer "+secret},30).get("reply")
 if not isinstance(answer,str) or not answer.strip():raise RuntimeError("Agent response must contain a non-empty reply.")
 send(sender,answer);append_audit(settings.audit_path,"whatsapp.replied",{"message_id":mid,"agent_id":agent["id"],"reply_sha256":hashlib.sha256(answer.encode()).hexdigest()})
async def read_webhook_body(request: Request, max_bytes: int = 1_000_000) -> bytes:
 chunks = []
 size = 0
 async for chunk in request.stream():
  size += len(chunk)
  if size > max_bytes:
   raise HTTPException(413, "Webhook payload exceeds the 1 MB limit.")
  chunks.append(chunk)
 return b"".join(chunks)


@router.post("/webhook")
async def webhook(request:Request):
 raw=await read_webhook_body(request);secret=env("NOVA_WHATSAPP_APP_SECRET");sig=request.headers.get("x-hub-signature-256","");expected="sha256="+hmac.new(secret.encode(),raw,"sha256").hexdigest() if secret else ""
 if not expected or not hmac.compare_digest(sig,expected):raise HTTPException(401,"Invalid webhook signature.")
 try:data=json.loads(raw)
 except json.JSONDecodeError as e:raise HTTPException(400,"Invalid JSON.") from e
 if not isinstance(data,dict) or data.get("object")!="whatsapp_business_account":return {"received":True}
 for entry in data.get("entry",[]):
  for change in entry.get("changes",[]):
   for msg in change.get("value",{}).get("messages",[]):
    if msg.get("type")!="text":continue
    mid=msg.get("id");sender=str(msg.get("from",""));body=msg.get("text",{}).get("body","")
    if not isinstance(mid,str) or not mid or not sender.isdigit() or not isinstance(body,str) or len(body)>4000:continue
    c=db()
    try:
     row=c.execute("SELECT status FROM whatsapp_events WHERE message_id=?",(mid,)).fetchone()
     if row and row["status"]=="sent":continue
     c.execute("INSERT INTO whatsapp_events VALUES(?,?,?) ON CONFLICT(message_id) DO UPDATE SET status='processing'",(mid,"processing",datetime.now(timezone.utc).isoformat()));c.commit()
    finally:c.close()
    state="sent"
    try:dispatch(sender,body,mid)
    except Exception as e:state="failed";append_audit(settings.audit_path,"whatsapp.failed",{"message_id":mid,"error":type(e).__name__})
    c=db()
    try:c.execute("UPDATE whatsapp_events SET status=? WHERE message_id=?",(state,mid));c.commit()
    finally:c.close()
 return {"received":True}
