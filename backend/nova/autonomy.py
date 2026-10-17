import json,re,sqlite3,uuid
from datetime import datetime,timezone
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from nova.config import settings
from nova.audit import append_audit
from nova.identity import compose_prompt
from nova.litert import chat,LiteRTError
from nova.agent_tools import execute,calculator
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
 settings.database_path.parent.mkdir(parents=True,exist_ok=True);c=sqlite3.connect(settings.database_path,timeout=10);c.row_factory=sqlite3.Row;c.execute("CREATE TABLE IF NOT EXISTS nova_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL)")
 c.execute("""CREATE TABLE IF NOT EXISTS autonomy_runs(
 id TEXT PRIMARY KEY,task_id TEXT NOT NULL,goal TEXT NOT NULL,status TEXT NOT NULL,
 plan_json TEXT NOT NULL,steps_json TEXT NOT NULL,verification_json TEXT NOT NULL,
 current_step INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 cancel_requested INTEGER NOT NULL DEFAULT 0)""")
 columns={str(r[1]) for r in c.execute("PRAGMA table_info(autonomy_runs)").fetchall()}
 if "cancel_requested" not in columns:c.execute("ALTER TABLE autonomy_runs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0")
 c.commit();return c
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
def validate_steps(ss,n):
 if not isinstance(ss,list) or not 1<=len(ss)<=n:raise ValueError("Invalid plan length.")
 clean=[]
 for i,s in enumerate(ss,1):
  if not isinstance(s,dict) or set(s)-{"tool","input","reason"}:raise ValueError("Step "+str(i)+" has an invalid shape.")
  tool=s.get("tool");inp=s.get("input")
  if tool not in ALLOWED or not isinstance(inp,dict):raise ValueError("Step "+str(i)+" uses an unknown tool or invalid input.")
  if not isinstance(s.get("reason",""),str) or len(s.get("reason",""))>300:raise ValueError("Step "+str(i)+" has an invalid reason.")
  if tool=="calculator":
   if set(inp)!={"expression"} or not isinstance(inp.get("expression"),str) or not inp["expression"].strip() or len(inp["expression"])>256:raise ValueError("Calculator step "+str(i)+" requires one expression of at most 256 characters.")
   try:calculator(inp["expression"])
   except (ValueError,SyntaxError,ZeroDivisionError,OverflowError) as e:raise ValueError("Calculator step "+str(i)+" failed preflight validation.") from e
  elif tool=="knowledge_search":
   if set(inp)!={"query"} or not isinstance(inp.get("query"),str) or not inp["query"].strip() or len(inp["query"])>1000:raise ValueError("Knowledge search step "+str(i)+" requires one query of at most 1000 characters.")
  clean.append({"tool":tool,"input":dict(inp),"reason":s.get("reason","")})
 return clean
def plan(goal,n):
 try:v=obj(chat(compose_prompt('Return only JSON {"steps":[{"tool":"calculator|knowledge_search","input":{},"reason":"..."}]}. Maximum '+str(n)+' steps. No shell or writes. Goal: '+goal),1000))
 except LiteRTError as e:raise HTTPException(503,str(e)) from e
 except (ValueError,json.JSONDecodeError) as e:raise HTTPException(502,"Invalid plan; no tools executed.") from e
 try:return validate_steps(v.get("steps"),n)
 except ValueError as e:raise HTTPException(502,"Plan rejected during preflight; no tools executed: "+str(e)) from e
@router.post("/plan")
def plan_only(req:Goal):return {"goal":req.goal,"steps":plan(req.goal,req.max_steps),"tools_executed":0}
def save_run(run_id,task_id,goal,status,steps,plan_steps,verification,current_step,created_at):
 c=db()
 try:
  c.execute("""INSERT INTO autonomy_runs(id,task_id,goal,status,plan_json,steps_json,verification_json,current_step,created_at,updated_at)
  VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,steps_json=excluded.steps_json,
  verification_json=excluded.verification_json,current_step=excluded.current_step,updated_at=excluded.updated_at""",
  (run_id,task_id,goal,status,json.dumps(plan_steps),json.dumps(steps),json.dumps(verification),current_step,created_at,datetime.now(timezone.utc).isoformat()))
  c.commit()
 finally:c.close()
def run_view(row):
 item=dict(row)
 for key in ("plan_json","steps_json","verification_json"):
  item[key.removesuffix("_json")]=json.loads(item.pop(key))
 return item
@router.get("/runs")
def run_history(limit:int=10):
 if limit<1 or limit>100:raise HTTPException(422,"limit must be between 1 and 100.")
 c=db()
 try:rows=c.execute("SELECT * FROM autonomy_runs ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
 finally:c.close()
 return [run_view(r) for r in rows]
@router.get("/runs/{run_id}")
def run_detail(run_id:str):
 c=db()
 try:row=c.execute("SELECT * FROM autonomy_runs WHERE id=?",(run_id,)).fetchone()
 finally:c.close()
 if row is None:raise HTTPException(404,"Autonomy run not found.")
 return run_view(row)
@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id:str):
 c=db()
 try:
  now=datetime.now(timezone.utc).isoformat()
  cur=c.execute("UPDATE autonomy_runs SET cancel_requested=1,updated_at=? WHERE id=? AND status='running' AND cancel_requested=0",(now,run_id));c.commit()
  row=c.execute("SELECT status,cancel_requested FROM autonomy_runs WHERE id=?",(run_id,)).fetchone()
 finally:c.close()
 if row is None:raise HTTPException(404,"Autonomy run not found.")
 if row["status"]!="running":raise HTTPException(409,"Only a running autonomy run can be cancelled.")
 append_audit(settings.audit_path,"autonomy.cancel_requested",{"run_id":run_id})
 return {"run_id":run_id,"status":"cancel_requested","cancel_requested":True,"message":"Cancellation is checked between tool steps; an already-running step may finish first."}
def recover_interrupted_runs():
 """Mark runs left active by a process restart; never replay side effects automatically."""
 c=db()
 try:
  now=datetime.now(timezone.utc).isoformat()
  rows=c.execute("SELECT id,task_id,current_step FROM autonomy_runs WHERE status='running'").fetchall()
  for row in rows:
   c.execute("UPDATE autonomy_runs SET status='interrupted',updated_at=? WHERE id=? AND status='running'",(now,row["id"]))
  c.commit()
 finally:c.close()
 for row in rows:
  try:
   update_task_status(row["task_id"],TaskStatusUpdate(status="failed",result="Autonomy run interrupted by process restart. Checkpoint preserved; automatic replay is disabled."))
  except (HTTPException,ValueError):
   pass
  append_audit(settings.audit_path,"autonomy.interrupted",{"run_id":row["id"],"task_id":row["task_id"],"checkpoint_step":row["current_step"]})
 return {"interrupted":len(rows),"run_ids":[row["id"] for row in rows]}
def cancel_requested(run_id):
 c=db()
 try:r=c.execute("SELECT cancel_requested FROM autonomy_runs WHERE id=?",(run_id,)).fetchone()
 finally:c.close()
 return bool(r and r["cancel_requested"])
@router.post("/run")
def run(req:Goal):
 c=cfg()
 if not c["enabled"]:raise HTTPException(409,"Autonomy disabled by default.")
 ss=plan(req.goal,min(req.max_steps,c["max_steps"]))
 task=create_task(TaskCreate(title=req.goal[:200],description=req.goal,plan=[x["tool"] for x in ss],max_attempts=1));tid=task["id"]
 update_task_status(tid,TaskStatusUpdate(status="planned"));update_task_status(tid,TaskStatusUpdate(status="in_progress"))
 run_id=str(uuid.uuid4());created=datetime.now(timezone.utc).isoformat();out=[];verification={"verified":False,"summary":"Not verified."}
 save_run(run_id,tid,req.goal,"running",out,ss,verification,0,created)
 for i,s in enumerate(ss):
  if cancel_requested(run_id):break
  try:out.append({"step":i+1,"tool":s["tool"],"reason":str(s.get("reason",""))[:300],"ok":True,"result":execute(type("CallProxy",(),{"name":s["tool"],"input":s.get("input",{})})())})
  except Exception as e:out.append({"step":i+1,"tool":s.get("tool","unknown"),"ok":False,"error":str(e)[:200]})
  save_run(run_id,tid,req.goal,"running",out,ss,verification,i+1,created)
  if not out[-1]["ok"]:break
 cancelled=cancel_requested(run_id)
 if c["verify_results"] and not cancelled:
  try:
   v=obj(chat(compose_prompt('Verify using only these outputs. JSON {"verified":boolean,"summary":"..."}. Goal: '+req.goal+" Outputs: "+json.dumps(out,default=str)[:6000]),400))
   verification={"verified":v.get("verified") is True,"summary":str(v.get("summary",""))[:500]}
  except Exception:verification={"verified":False,"summary":"Verifier failed; not verified."}
 cancelled=cancel_requested(run_id)
 done=not cancelled and bool(out) and all(x["ok"] for x in out) and (verification["verified"] if c["verify_results"] else True)
 result={"goal":req.goal,"steps":out,"verification":verification,"completed":done,"cancelled":cancelled}
 final_status="cancelled" if cancelled else ("completed" if done else "failed")
 save_run(run_id,tid,req.goal,final_status,out,ss,verification,len(out),created)
 update_task_status(tid,TaskStatusUpdate(status=final_status,result=json.dumps(result)[:20000]))
 append_audit(settings.audit_path,"autonomy.finished",{"run_id":run_id,"task_id":tid,"completed":done,"cancelled":cancelled,"verified":verification["verified"]})
 return {"run_id":run_id,"task_id":tid,**result}
