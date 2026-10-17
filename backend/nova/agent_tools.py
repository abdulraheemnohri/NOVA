import ast,math
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from nova.audit import append_audit
from nova.config import settings
from nova.policy import evaluate_tool
from nova.knowledge import SearchRequest,search_knowledge
router=APIRouter(prefix="/api/agent/tools",tags=["agent tools"])
class Call(BaseModel):
 model_config=ConfigDict(extra="forbid")
 name:str=Field(min_length=1,max_length=60);input:dict={}
def calculator(s):
 if not isinstance(s,str) or len(s)>256:raise ValueError("Invalid expression.")
 t=ast.parse(s,mode="eval")
 if len(list(ast.walk(t)))>50:raise ValueError("Expression too complex.")
 def ev(n):
  if isinstance(n,ast.Expression):return ev(n.body)
  if isinstance(n,ast.Constant) and type(n.value) in (int,float) and abs(n.value)<=1e12:return n.value
  if isinstance(n,ast.UnaryOp) and isinstance(n.op,(ast.UAdd,ast.USub)):
   v=ev(n.operand);return v if isinstance(n.op,ast.UAdd) else -v
  if isinstance(n,ast.BinOp) and isinstance(n.op,(ast.Add,ast.Sub,ast.Mult,ast.Div,ast.FloorDiv,ast.Mod,ast.Pow)):
   a,b=ev(n.left),ev(n.right)
   if isinstance(n.op,ast.Pow) and abs(b)>10:raise ValueError("Exponent too large.")
   v={ast.Add:lambda:a+b,ast.Sub:lambda:a-b,ast.Mult:lambda:a*b,ast.Div:lambda:a/b,ast.FloorDiv:lambda:a//b,ast.Mod:lambda:a%b,ast.Pow:lambda:a**b}[type(n.op)]()
   if not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>1e12:raise ValueError("Result out of range.")
   return v
  raise ValueError("Only numeric arithmetic is allowed.")
 return ev(t)
@router.get("")
def catalog():return {"tools":[{"name":"calculator"},{"name":"knowledge_search"}],"shell":False,"network":False,"writes":False}
@router.post("/execute")
def execute(req:Call):
 d=evaluate_tool(req.name)
 if not d.allowed or d.requires_approval:raise HTTPException(403,d.reason)
 try:
  if req.name=="calculator":r={"result":calculator(req.input.get("expression"))}
  elif req.name=="knowledge_search":
   q=req.input.get("query")
   if not isinstance(q,str) or not q.strip() or len(q)>1000:raise ValueError("Invalid query.")
   r=search_knowledge(SearchRequest(query=q,limit=5))
  else:raise ValueError("Unknown tool; default deny.")
 except (ValueError,SyntaxError,ZeroDivisionError,OverflowError) as e:
  append_audit(settings.audit_path,"agent.tool.failed",{"tool":req.name});raise HTTPException(422,str(e)) from e
 append_audit(settings.audit_path,"agent.tool.executed",{"tool":req.name});return {"tool":req.name,**r}
