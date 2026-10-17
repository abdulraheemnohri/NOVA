import json,re,sqlite3
from datetime import datetime,timezone
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from nova.config import settings
from nova.audit import append_audit
from nova.identity import compose_prompt
from nova.litert import chat,LiteRTError
from nova.agent_tools import execute
from nova.tasks import TaskCreate,TaskStatusUpdate,create_task,update_task_status
router=APIRouter(prefix="/api/autonomy",tags=["autonomy"])
ALLOWED={"calculator","knowledge_search"}
class Config(BaseModel):
 model_config=ConfigDict(extra="forbid")
 enabled:bool=False;max_steps:int=Field(default=4,ge=1,le=8);verify_results:bool=True
class Goal(BaseModel):
 model_config=ConfigDict(extra="forbid")
 goal:str=Field(min_length=3,max_length=2000);max_steps:int=Field(default=4,ge=1,le=8)
def db():
 settings.database_path.parent.mkdir(parents=True,exist_ok=True);c=sqlite3.connect(settings.database_path,timeout=10);c.row_factory=sqlite3.Row;c.execute("CREATE TABLE IF NOT EXISTS nova_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL)");return c
def cfg():
 c=db()
 try:r={x["key"]:x["value"] for x in c.execute("SELECT key,value FROM nova_settings WHERE key LIKE 'autonomy_%'").fetchall()}
 finally:c.close()
 try:return {"enabled":r.get("autonomy_enabled","false")=="true","max_steps":max(1,min(8,int(r.get("autonomy_max_steps","4")))),"verify_results":r.get("autonomy_verify_results","true")=="true"}
 except ValueError:return {"enabled":False,"max_steps":4,"verify_results":True}
@router.get("/settings")
def get_cfg():return {**cfg(),"tools":sorted(ALLOWED),"shell":False,"network":False,"writes":False}
@router.put("/settings")
def set_cfg(req:Config):
 now=datetime.now(timezone.utc).isoformat();c=db()
 try:c.executemany("INSERT INTO nova_settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",[("autonomy_enabled",str(req.enabled).lower(),now),("autonomy_max_steps",str(req.max_steps),now),("autonomy_verify_results",str(req.verify_results).lower(),now)]);c.commit()
 finally:c.close()
 append_audit(settings.audit_path,"autonomy.settings.updated",req.model_dump());return get_cfg()
def obj(s):
 s=re.sub(r"^\x60{3}(?:json)?\s*|\s*\x60{3}$","",s.strip(),flags=re.I);v=json.loads(s)
 if not isinstance(v,dict):raise ValueError("JSON object required")
 return v
def plan(goal,n):
 try:v=obj(chat(compose_prompt('Return only JSON {"steps":[{"tool":"calculator|knowledge_search","input":{},"reason":"..."}]}. Maximum '+str(n)+' steps. No shell or writes. Goal: '+goal),1000))
 except LiteRTError as e:raise HTTPException(503,str(e)) from e
 except (ValueError,json.JSONDecodeError) as e:raise HTTPException(502,"Invalid plan; no tools executed.") from e
 ss=v.get("steps")
 if not isinstance(ss,list) or not 1<=len(ss)<=n:raise HTTPException(502,"Invalid plan length.")
 for s in ss:
  if not isinstance(s,dict) or s.get("tool") not in ALLOWED or not isinstance(s.get("input",{}),dict):raise HTTPException(502,"Unknown tool; no steps executed.")
 return ss
@router.post("/plan")
def plan_only(req:Goal):return {"goal":req.goal,"steps":plan(req.goal,req.max_steps),"tools_executed":0}
@router.post("/run")
def run(req:Goal):
 c=cfg()
 if not c["enabled"]:raise HTTPException(409,"Autonomy disabled by default.")
 ss=plan(req.goal,min(req.max_steps,c["max_steps"]));task=create_task(TaskCreate(title=req.goal[:200],description=req.goal,plan=[x["tool"] for x in ss],max_attempts=1));tid=task["id"]
 update_task_status(tid,TaskStatusUpdate(status="planned"));update_task_status(tid,TaskStatusUpdate(status="in_progress"));out=[]
 for i,s in enumerate(ss):
  try:out.append({"step":i+1,"ok":True,"result":execute(type("CallProxy",(),{"name":s["tool"],"input":s.get("input",{})})())})
  except Exception as e:out.append({"step":i+1,"ok":False,"error":str(e)[:200]});break
 verified=False;summary="Not verified."
 if c["verify_results"]:
  try:v=obj(chat(compose_prompt('Verify using only these outputs. JSON {"verified":boolean,"summary":"..."}. Goal: '+req.goal+" Outputs: "+json.dumps(out,default=str)[:6000]),400));verified=v.get("verified") is True;summary=str(v.get("summary",""))[:500]
  except Exception:summary="Verifier failed; not verified."
 done=bool(out) and all(x["ok"] for x in out) and (verified if c["verify_results"] else True);result={"goal":req.goal,"steps":out,"verification":{"verified":verified,"summary":summary},"completed":done}
 update_task_status(tid,TaskStatusUpdate(status="completed" if done else "failed",result=json.dumps(result)[:20000]));append_audit(settings.audit_path,"autonomy.finished",{"task_id":tid,"completed":done,"verified":verified});return {"task_id":tid,**result}
