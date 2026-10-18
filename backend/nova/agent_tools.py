import ast,math,base64,json,csv,io,re
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
def catalog():return {"tools":[{"name":"calculator","input_schema":{"expression":"string"}},{"name":"knowledge_search","input_schema":{"query":"string"}},{"name":"text_stats","input_schema":{"text":"string"}},{"name":"json_format","input_schema":{"json":"string"}},{"name":"base64_encode","input_schema":{"text":"string"}},{"name":"base64_decode","input_schema":{"encoded":"string"}},{"name":"csv_summary","input_schema":{"csv":"string"}},{"name":"markdown_outline","input_schema":{"markdown":"string"}}],"shell":False,"network":False,"writes":False}
@router.post("/execute")
def execute(req:Call):
 d=evaluate_tool(req.name)
 if not d.allowed or d.requires_approval:raise HTTPException(403,d.reason)
 try:
  if req.name=="calculator":r={"result":calculator(req.input.get("expression"))}
  elif req.name=="text_stats":
   value=req.input.get("text")
   if not isinstance(value,str) or len(value)>10000:raise ValueError("Text must be a string of at most 10000 characters.")
   r={"characters":len(value),"words":len(value.split()),"lines":len(value.splitlines()) if value else 0}
  elif req.name=="json_format":
   value=req.input.get("json")
   if not isinstance(value,str) or len(value)>100000:raise ValueError("JSON must be a string of at most 100000 characters.")
   try: parsed=json.loads(value)
   except json.JSONDecodeError as exc: raise ValueError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}.") from exc
   formatted=json.dumps(parsed,ensure_ascii=False,indent=2)
   if len(formatted)>200000:raise ValueError("Formatted JSON exceeds output limit.")
   r={"formatted":formatted,"valid":True}
  elif req.name=="base64_encode":
   value=req.input.get("text")
   if not isinstance(value,str) or len(value)>100000:raise ValueError("Text must be a string of at most 100000 characters.")
   r={"encoded":base64.b64encode(value.encode("utf-8")).decode("ascii")}
  elif req.name=="base64_decode":
   value=req.input.get("encoded")
   if not isinstance(value,str) or len(value)>140000:raise ValueError("Encoded input must be a string of at most 140000 characters.")
   try: decoded=base64.b64decode(value,validate=True).decode("utf-8")
   except (ValueError,UnicodeDecodeError) as exc: raise ValueError("Input must be valid Base64 containing UTF-8 text.") from exc
   r={"decoded":decoded}
  elif req.name=="csv_summary":
   value=req.input.get("csv")
   if not isinstance(value,str) or len(value)>100000:raise ValueError("CSV must be a string of at most 100000 characters.")
   try:
    reader=csv.DictReader(io.StringIO(value,newline=""))
    headers=reader.fieldnames
    if not headers or any(not h or len(h)>200 for h in headers):raise ValueError("CSV must include a header row with non-empty column names.")
    if len(headers)>100 or len(set(headers))!=len(headers):raise ValueError("CSV must have at most 100 unique columns.")
    rows=[]
    for row in reader:
     if len(rows)>=2000:raise ValueError("CSV is limited to 2000 data rows.")
     if None in row:raise ValueError("A CSV row has more values than the header.")
     rows.append(row)
   except csv.Error as exc:raise ValueError("Invalid CSV input.") from exc
   columns=[]
   for name in headers:
    values=[(row.get(name) or "").strip() for row in rows]
    present=[v for v in values if v]
    numeric=sum(1 for v in present if re.fullmatch(r"[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?",v))
    boolean=sum(1 for v in present if v.lower() in ("true","false","yes","no"))
    kind="empty" if not present else ("number" if numeric==len(present) else ("boolean" if boolean==len(present) else "text"))
    columns.append({"name":name,"non_empty":len(present),"missing":len(rows)-len(present),"inferred_type":kind})
   r={"row_count":len(rows),"column_count":len(headers),"columns":columns,"truncated":False}
  elif req.name=="markdown_outline":
   value=req.input.get("markdown")
   if not isinstance(value,str) or len(value)>100000:raise ValueError("Markdown must be a string of at most 100000 characters.")
   headings=[]
   for line_number,line in enumerate(value.splitlines(),1):
    match=re.match(r"^ {0,3}(#{1,6})[ \\t]+(.+?)\\s*#*\\s*$",line)
    if match:
     headings.append({"level":len(match.group(1)),"text":match.group(2).strip(),"line":line_number})
     if len(headings)>500:raise ValueError("Markdown outline is limited to 500 headings.")
   r={"heading_count":len(headings),"headings":headings}
  elif req.name=="knowledge_search":
   q=req.input.get("query")
   if not isinstance(q,str) or not q.strip() or len(q)>1000:raise ValueError("Invalid query.")
   r=search_knowledge(SearchRequest(query=q,limit=5))
  else:raise ValueError("Unknown tool; default deny.")
 except (ValueError,SyntaxError,ZeroDivisionError,OverflowError) as e:
  append_audit(settings.audit_path,"agent.tool.failed",{"tool":req.name});raise HTTPException(422,str(e)) from e
 append_audit(settings.audit_path,"agent.tool.executed",{"tool":req.name});return {"tool":req.name,**r}
