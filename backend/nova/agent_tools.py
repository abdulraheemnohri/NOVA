import ast,math,base64,json,csv,io,re
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from nova.audit import append_audit
from nova.config import settings
from nova.policy import evaluate_tool
from nova.knowledge import SearchRequest,search_knowledge
from nova.web_search import google_search
router=APIRouter(prefix="/api/agent/tools",tags=["agent tools"])
class Call(BaseModel):
 model_config=ConfigDict(extra="forbid")
 name:str=Field(min_length=1,max_length=60);input:dict={}

# Each registered deterministic tool accepts exactly one bounded string field.
# Keeping the schema at the API boundary prevents silently ignored or oversized inputs.
_TOOL_INPUT_LIMITS = {
 "calculator": {"expression": 256},
 "knowledge_search": {"query": 1000},
 "web_search": {"query": 400},
 "text_stats": {"text": 10000},
 "json_format": {"json": 100000},
 "base64_encode": {"text": 100000},
 "base64_decode": {"encoded": 140000},
 "csv_summary": {"csv": 100000},
 "markdown_outline": {"markdown": 100000},
}

def _validate_tool_input(name: str, value: dict) -> None:
 schema = _TOOL_INPUT_LIMITS.get(name)
 if schema is None:
  return  # Authorization below remains responsible for default-denying unknown tools.
 if set(value) != set(schema):
  expected = ", ".join(sorted(schema))
  raise HTTPException(422, "Tool input must contain exactly these field(s): " + expected + ".")
 for field_name, limit in schema.items():
  field_value = value[field_name]
  if not isinstance(field_value, str):
   raise HTTPException(422, "Tool input '" + field_name + "' must be a string.")
  if len(field_value) > limit:
   raise HTTPException(422, "Tool input '" + field_name + "' exceeds the " + str(limit) + "-character limit.")
def _is_number(value):
 try:
  float(value)
  return True
 except ValueError:
  return False

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
def catalog():return {"tools":[{"name":"calculator","input_schema":{"expression":"string"}},{"name":"knowledge_search","input_schema":{"query":"string"}},{"name":"web_search","input_schema":{"query":"string"}},{"name":"text_stats","input_schema":{"text":"string"}},{"name":"json_format","input_schema":{"json":"string"}},{"name":"base64_encode","input_schema":{"text":"string"}},{"name":"base64_decode","input_schema":{"encoded":"string"}},{"name":"csv_summary","input_schema":{"csv":"string"}},{"name":"markdown_outline","input_schema":{"markdown":"string"}}],"shell":False,"network":True,"writes":False}
@router.post("/execute")
def execute(req:Call):
 d=evaluate_tool(req.name)
 if not d.allowed or d.requires_approval:raise HTTPException(403,d.reason)
 _validate_tool_input(req.name, req.input)
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
    numeric=sum(1 for v in present if _is_number(v))
    boolean=sum(1 for v in present if v.lower() in ("true","false","yes","no"))
    kind="empty" if not present else ("number" if numeric==len(present) else ("boolean" if boolean==len(present) else "text"))
    columns.append({"name":name,"non_empty":len(present),"missing":len(rows)-len(present),"inferred_type":kind})
   r={"row_count":len(rows),"column_count":len(headers),"columns":columns,"truncated":False}
  elif req.name=="markdown_outline":
   value=req.input.get("markdown")
   if not isinstance(value,str) or len(value)>100000:raise ValueError("Markdown must be a string of at most 100000 characters.")
   headings=[]
   for line_number,line in enumerate(value.splitlines(),1):
    stripped=line.lstrip(" ")
    indent=len(line)-len(stripped)
    if indent<=3 and stripped.startswith("#"):
     marker=stripped.split(" ",1)[0]
     if 1<=len(marker)<=6 and set(marker)=={"#"} and len(stripped)>len(marker) and stripped[len(marker)].isspace():
      title=stripped[len(marker):].strip().strip("#").strip()
      if title: headings.append({"level":len(marker),"text":title,"line":line_number})
     if len(headings)>500:raise ValueError("Markdown outline is limited to 500 headings.")
   r={"heading_count":len(headings),"headings":headings}
  elif req.name=="knowledge_search":
   q=req.input.get("query")
   if not isinstance(q,str) or not q.strip() or len(q)>1000:raise ValueError("Invalid query.")
   r=search_knowledge(SearchRequest(query=q,limit=5))
  elif req.name=="web_search":
   q=req.input.get("query")
   if not isinstance(q,str) or not q.strip() or len(q)>400:raise ValueError("Search query must be 1-400 characters.")
   r=google_search(q, limit=5)
  else:raise ValueError("Unknown tool; default deny.")
 except (ValueError,SyntaxError,ZeroDivisionError,OverflowError) as e:
  append_audit(settings.audit_path,"agent.tool.failed",{"tool":req.name});raise HTTPException(422,str(e)) from e
 append_audit(settings.audit_path,"agent.tool.executed",{"tool":req.name});return {"tool":req.name,**r}
