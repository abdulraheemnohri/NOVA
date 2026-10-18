import {useCallback,useEffect,useRef,useState,type FormEvent} from "react";
import {Activity,Plus,Play,RefreshCw,ShieldCheck,Square,Workflow} from "lucide-react";
import {PageHeader,StatusBadge} from "../components/ui";

const API="http://127.0.0.1:8000/api/workflows";
type Tool="calculator"|"knowledge_search";
type Condition="always"|"on_success"|"on_failure";
type StepDraft={tool:Tool;value:string;when:Condition};
type Step={tool:Tool;input:Record<string,string>;when:Condition};
type Definition={id:string;name:string;steps:Step[];created_at:string;updated_at:string};
type RunStep={index:number;tool:string;status:string;when:string;result?:unknown;error?:string;reason?:string};
type Run={id:string;workflow_id:string;status:string;current_step:number;steps:RunStep[];created_at:string;updated_at:string;finished_at?:string};
const inputClass="w-full rounded-lg border border-white/10 bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-300/40";
const buttonClass="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm text-slate-200 hover:bg-white/5 disabled:opacity-40";

export default function WorkflowEnginePage({apiFetch,onError}:{apiFetch:(url:string,init?:RequestInit)=>Promise<Response>;onError:(s:string)=>void}){
 const apiFetchRef=useRef(apiFetch);
 apiFetchRef.current=apiFetch;
 const [definitions,setDefinitions]=useState<Definition[]>([]);
 const [runs,setRuns]=useState<Run[]>([]);
 const [name,setName]=useState("");
 const [drafts,setDrafts]=useState<StepDraft[]>([{tool:"calculator",value:"1 + 1",when:"always"}]);
 const [loading,setLoading]=useState(false);
 const [saving,setSaving]=useState(false);
 const [running,setRunning]=useState<string|null>(null);
 const [cancelling,setCancelling]=useState<string|null>(null);
 const hasRunning=runs.some(run=>run.status==="running");
 const refresh=useCallback(async()=>{
  setLoading(true);
  try{
   const [wr,rr]=await Promise.all([apiFetchRef.current(API),apiFetchRef.current(API+"/runs?limit=50")]);
   const wd=await wr.json(),rd=await rr.json();
   if(!wr.ok)throw Error(wd.detail||"Could not load workflows");
   if(!rr.ok)throw Error(rd.detail||"Could not load workflow runs");
   setDefinitions(wd.workflows||[]);
   setRuns(rd.runs||[]);
  }catch(e){onError(e instanceof Error?e.message:"Workflow engine unavailable")}
  finally{setLoading(false)}
 },[onError]);
 useEffect(()=>{void refresh()},[refresh]);
 useEffect(()=>{
  if(!hasRunning)return;
  const timer=window.setInterval(()=>{void refresh()},1500);
  return()=>window.clearInterval(timer);
 },[hasRunning,refresh]);
 function updateStep(index:number,patch:Partial<StepDraft>){
  setDrafts(current=>current.map((step,i)=>i===index?{...step,...patch}:step));
 }
 async function create(event:FormEvent){
  event.preventDefault();setSaving(true);
  try{
   const payload={name,steps:drafts.map(step=>({tool:step.tool,when:step.when,input:step.tool==="calculator"?{expression:step.value}:{query:step.value}}))};
   const response=await apiFetchRef.current(API,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
   const data=await response.json();
   if(!response.ok)throw Error(data.detail||"Could not save workflow");
   setName("");setDrafts([{tool:"calculator",value:"1 + 1",when:"always"}]);
   onError("");await refresh();
  }catch(e){onError(e instanceof Error?e.message:"Could not save workflow")}
  finally{setSaving(false)}
 }
 async function run(id:string){
  setRunning(id);
  try{
   const response=await apiFetchRef.current(API+"/"+encodeURIComponent(id)+"/run",{method:"POST"});
   const data=await response.json();
   if(!response.ok)throw Error(data.detail||"Workflow run failed");
   onError("");await refresh();
  }catch(e){onError(e instanceof Error?e.message:"Could not run workflow");await refresh()}
  finally{setRunning(null)}
 }
 async function cancel(id:string){
  setCancelling(id);
  try{
   const response=await apiFetchRef.current(API+"/runs/"+encodeURIComponent(id)+"/cancel",{method:"POST"});
   const data=await response.json();
   if(!response.ok)throw Error(data.detail||"Could not cancel workflow");
   onError("");await refresh();
  }catch(e){onError(e instanceof Error?e.message:"Could not cancel workflow")}
  finally{setCancelling(null)}
 }
 return <section className="space-y-5">
  <div className="panel p-5">
   <PageHeader title="Workflow Engine" description="Create bounded local workflows, inspect checkpoints, and request cancellation between tool calls." actions={<button className={buttonClass} onClick={()=>void refresh()} disabled={loading}><RefreshCw size={15}/>{loading?"Refreshing…":"Refresh"}</button>}/>
   <div className="mt-3 flex flex-wrap gap-2"><StatusBadge status="Local tools only" tone="good"/><StatusBadge status="Default deny" tone="neutral"/><StatusBadge status="Checkpointed runs" tone="info"/></div>
   <p className="mt-3 text-xs text-slate-400">Only calculator and local knowledge search are available. Cancellation takes effect between calls; a currently executing call is allowed to finish.</p>
  </div>
  <div className="panel p-5">
   <h3 className="mb-4 flex items-center gap-2 font-semibold"><Plus size={17} className="text-cyan-300"/>Create workflow</h3>
   <form onSubmit={create} className="space-y-4">
    <label className="block space-y-1 text-sm"><span className="text-slate-400">Workflow name</span><input className={inputClass} value={name} onChange={e=>setName(e.target.value)} minLength={3} maxLength={80} required placeholder="e.g. Verify local calculation"/></label>
    {drafts.map((step,index)=><div key={index} className="rounded-xl border border-white/10 p-3">
     <div className="mb-3 flex items-center justify-between"><span className="text-sm font-medium">Step {index+1}</span>{drafts.length>1&&<button type="button" className="text-xs text-rose-300" onClick={()=>setDrafts(v=>v.filter((_,i)=>i!==index))}>Remove</button>}</div>
     <div className="grid gap-3 md:grid-cols-3">
      <label className="space-y-1 text-xs text-slate-400">Tool<select className={inputClass} value={step.tool} onChange={e=>updateStep(index,{tool:e.target.value as Tool,value:e.target.value==="calculator"?"1 + 1":"local knowledge"})}><option value="calculator">Calculator</option><option value="knowledge_search">Local knowledge search</option></select></label>
      <label className="space-y-1 text-xs text-slate-400">Run condition<select className={inputClass} value={step.when} onChange={e=>updateStep(index,{when:e.target.value as Condition})}><option value="always">Always</option><option value="on_success">After success</option><option value="on_failure">After failure</option></select></label>
      <label className="space-y-1 text-xs text-slate-400">{step.tool==="calculator"?"Expression":"Search query"}<input className={inputClass} value={step.value} onChange={e=>updateStep(index,{value:e.target.value})} maxLength={step.tool==="calculator"?256:1000} required/></label>
     </div>
    </div>)}
    <div className="flex flex-wrap gap-2"><button type="button" className={buttonClass} disabled={drafts.length>=10} onClick={()=>setDrafts(v=>[...v,{tool:"calculator",value:"1 + 1",when:"on_success"}])}><Plus size={15}/>Add step</button><button className="inline-flex items-center gap-2 rounded-lg bg-cyan-300 px-3 py-2 text-sm font-semibold text-slate-950 disabled:opacity-40" disabled={saving||!name.trim()||drafts.some(s=>!s.value.trim())}><ShieldCheck size={15}/>{saving?"Saving…":"Save workflow"}</button></div>
   </form>
  </div>
  <div className="panel p-5">
   <h3 className="mb-3 flex items-center gap-2 font-semibold"><Workflow size={17} className="text-cyan-300"/>Saved workflows <span className="text-xs text-slate-500">{definitions.length}</span></h3>
   {definitions.length===0?<p className="text-sm text-slate-500">No workflows saved yet.</p>:<div className="space-y-2">{definitions.map(def=><div key={def.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 p-3"><div><div className="font-medium">{def.name}</div><div className="mt-1 text-xs text-slate-500">{def.steps.length} steps · {def.steps.map(s=>s.tool).join(" → ")}</div></div><button className={buttonClass} disabled={running!==null} onClick={()=>void run(def.id)}><Play size={15}/>{running===def.id?"Running…":"Run"}</button></div>)}</div>}
  </div>
  <div className="panel p-5">
   <h3 className="mb-3 flex items-center gap-2 font-semibold"><Activity size={17} className="text-cyan-300"/>Execution history <span className="text-xs text-slate-500">{runs.length}</span></h3>
   {runs.length===0?<p className="text-sm text-slate-500">No execution history yet.</p>:<div className="space-y-3">{runs.map(run=><div key={run.id} className="rounded-xl border border-white/10 p-3">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><div className="font-mono text-xs text-slate-400">{run.id.slice(0,8)} · step {run.current_step}</div><div className="mt-1 text-sm">{run.status}</div></div><div className="flex items-center gap-2"><StatusBadge status={run.status} tone={run.status==="succeeded"?"good":run.status==="running"?"info":run.status==="cancelled"?"neutral":"warn"}/>{run.status==="running"&&<button className={buttonClass} disabled={cancelling===run.id} onClick={()=>void cancel(run.id)}><Square size={13}/>{cancelling===run.id?"Requesting…":"Cancel"}</button>}</div></div>
    {run.steps?.length>0&&<div className="mt-3 space-y-1">{run.steps.map((step,i)=><div key={i} className="flex flex-wrap justify-between gap-2 text-xs"><span className="text-slate-400">#{step.index} {step.tool} · {step.when}</span><span className={step.status==="failure"?"text-rose-300":step.status==="success"?"text-emerald-300":"text-slate-500"}>{step.status}{step.error?": "+step.error:""}</span></div>)}</div>}
   </div>)}</div>}
  </div>
 </section>
}
