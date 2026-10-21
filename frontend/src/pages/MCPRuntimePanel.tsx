import {useEffect,useState} from "react";
import {Activity,Play,Power,RefreshCw,ShieldCheck,TerminalSquare} from "lucide-react";
import {PageHeader} from "../components/ui";

type MCP = {id:string;name:string;enabled:boolean;config:Record<string,unknown>};
type Tool = {name:string;description:string;read_only:boolean};
type Props = {apiFetch:(url:string,init?:RequestInit)=>Promise<Response>;onError:(message:string)=>void};
const API="http://127.0.0.1:8000/api/integrations";

export default function MCPRuntimePanel({apiFetch,onError}:Props){
  const [items,setItems]=useState<MCP[]>([]);
  const [connected,setConnected]=useState<Record<string,boolean>>({});
  const [tools,setTools]=useState<Record<string,Tool[]>>({});
  const [busy,setBusy]=useState<string|null>(null);
  const [selected,setSelected]=useState("");
  const [toolName,setToolName]=useState("");
  const [args,setArgs]=useState("{}");
  const [confirmEffects,setConfirmEffects]=useState(false);
  const [result,setResult]=useState("");
  async function json(path:string,init?:RequestInit){
    const r=await apiFetch(API+path,init);
    const data=await r.json().catch(()=>({}));
    if(!r.ok)throw Error(data.detail||"MCP runtime request failed");
    return data;
  }
  async function refresh(){
    try{
      const data=await json("/mcp");
      const next=(data.items||[]) as MCP[];
      setItems(next);
      for(const item of next){
        try{
          const status=await json("/mcp/"+item.id+"/status");
          setConnected(prev=>({...prev,[item.id]:!!status.connected}));
          if(status.connected){
            const discovered=await json("/mcp/"+item.id+"/tools");
            setTools(prev=>({...prev,[item.id]:discovered.items||[]}));
          }
        }catch{/* disconnected entries remain usable */}
      }
    }catch(e){onError(e instanceof Error?e.message:String(e))}
  }
  useEffect(()=>{void refresh()},[]);
  async function connect(item:MCP){
    setBusy(item.id);setResult("");
    try{
      const data=await json("/mcp/"+item.id+"/connect",{method:"POST"});
      setConnected(prev=>({...prev,[item.id]:!!data.connected}));
      setTools(prev=>({...prev,[item.id]:data.tools||[]}));
      setSelected(item.id);
    }catch(e){onError(e instanceof Error?e.message:String(e))}
    finally{setBusy(null)}
  }
  async function disconnect(item:MCP){
    setBusy(item.id);
    try{
      await json("/mcp/"+item.id+"/disconnect",{method:"POST"});
      setConnected(prev=>({...prev,[item.id]:false}));
      setTools(prev=>({...prev,[item.id]:[]}));
      setResult("");
    }catch(e){onError(e instanceof Error?e.message:String(e))}
    finally{setBusy(null)}
  }
  async function invoke(){
    if(!selected||!toolName)return;
    let parsed:Record<string,unknown>;
    try{parsed=JSON.parse(args);if(!parsed||Array.isArray(parsed)||typeof parsed!=="object")throw Error("Arguments must be a JSON object.")}catch(e){onError(e instanceof Error?e.message:"Invalid JSON arguments");return}
    setBusy("call");setResult("");
    try{
      const data=await json("/mcp/"+selected+"/tools/"+encodeURIComponent(toolName)+"/call",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({arguments:parsed,confirm_side_effects:confirmEffects})});
      setResult(JSON.stringify(data.result,null,2));
      setConfirmEffects(false);
    }catch(e){onError(e instanceof Error?e.message:String(e))}
    finally{setBusy(null)}
  }
  const selectedTools=tools[selected]||[];
  const chosenTool=selectedTools.find(t=>t.name===toolName);
  return <div className="panel space-y-4 p-4">
    <PageHeader title="MCP Runtime" description="Connect enabled stdio or Streamable HTTP servers, discover tools, and invoke them explicitly. Stdio servers run as child processes; remote servers use JSON-RPC over HTTP(S)." actions={<button onClick={()=>void refresh()} className="rounded-xl border border-white/10 px-3 py-2 text-sm"><RefreshCw size={14} className="mr-2 inline"/>Refresh</button>}/>
    <div className="rounded-xl border border-amber-200/20 bg-amber-200/[.03] p-3 text-xs leading-5 text-amber-100/80"><ShieldCheck size={14} className="mr-2 inline"/>Only connect servers you trust. Stdio MCP servers execute with NOVA's operating-system user permissions. Remote MCP uses HTTPS except for loopback tests, rejects redirects, bounds requests/responses, and can read bearer credentials from environment variables. Tools not marked read-only require explicit confirmation below.</div>
    <div className="space-y-2">{items.filter(x=>["stdio","streamable_http"].includes(String(x.config?.transport||"stdio"))).map(item=><div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 p-3">
      <div className="min-w-0"><div className="flex flex-wrap items-center gap-2 font-medium">{item.name}<span className={"rounded-full px-2 py-0.5 text-[10px] "+(connected[item.id]?"bg-emerald-300/10 text-emerald-200":"bg-white/5 text-slate-400")}>{connected[item.id]?"Connected":"Disconnected"}</span>{!item.enabled&&<span className="text-[10px] text-amber-200">Disabled</span>}</div><p className="mt-1 break-all text-xs text-slate-500">{item.config?.transport==="stdio"?String(item.config?.command||"")+" "+(Array.isArray(item.config?.args)?item.config.args.join(" "):""):String(item.config?.endpoint||"")}</p></div>
      <div className="flex gap-2">{connected[item.id]?<button onClick={()=>void disconnect(item)} disabled={busy===item.id} className="rounded-lg border border-white/10 px-3 py-2 text-xs"><Power size={13} className="mr-1 inline"/>Disconnect</button>:<button onClick={()=>void connect(item)} disabled={busy!==null||!item.enabled} className="rounded-lg bg-cyan-300 px-3 py-2 text-xs font-semibold text-slate-950"><Play size={13} className="mr-1 inline"/>{busy===item.id?"Connecting…":"Connect"}</button>}</div>
    </div>)}
    {items.filter(x=>["stdio","streamable_http"].includes(String(x.config?.transport||"stdio"))).length===0&&<p className="text-sm text-slate-500">Add a stdio MCP server above, enable it, then connect it here.</p>}</div>
    {Object.values(connected).some(Boolean)&&<div className="space-y-3 border-t border-white/10 pt-4">
      <label className="block text-xs text-slate-400">Connected server<select value={selected} onChange={e=>{setSelected(e.target.value);setToolName("");setResult("")}} className="mt-1 w-full rounded-xl border border-white/10 bg-[#101827] p-3 text-sm">{items.filter(x=>connected[x.id]).map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
      <div className="flex items-center gap-2 text-xs text-slate-400"><Activity size={14}/>{selectedTools.length} discovered tool(s)</div>
      <label className="block text-xs text-slate-400">Tool<select value={toolName} onChange={e=>{setToolName(e.target.value);setConfirmEffects(false)}} className="mt-1 w-full rounded-xl border border-white/10 bg-[#101827] p-3 text-sm"><option value="">Choose a tool…</option>{selectedTools.map(t=><option key={t.name} value={t.name}>{t.name}{t.read_only?" · read-only":" · may change data"}</option>)}</select></label>
      {chosenTool&&<p className="text-xs text-slate-400">{chosenTool.description||"No description supplied by the server."}</p>}
      <label className="block text-xs text-slate-400">Arguments (JSON object)<textarea value={args} onChange={e=>setArgs(e.target.value)} rows={4} className="mt-1 w-full rounded-xl border border-white/10 bg-black/20 p-3 font-mono text-xs"/></label>
      {chosenTool&&!chosenTool.read_only&&<label className="flex items-start gap-2 text-xs text-amber-100"><input type="checkbox" checked={confirmEffects} onChange={e=>setConfirmEffects(e.target.checked)}/>I explicitly approve invoking this tool, which may modify data or cause side effects.</label>}
      <button onClick={()=>void invoke()} disabled={!toolName||busy!==null||!!(chosenTool&&!chosenTool.read_only&&!confirmEffects)} className="rounded-xl bg-cyan-300 px-4 py-2.5 text-sm font-semibold text-slate-950"><TerminalSquare size={14} className="mr-2 inline"/>{busy==="call"?"Calling…":"Call tool"}</button>
      {result&&<pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-white/10 bg-black/30 p-3 text-xs">{result}</pre>}
    </div>}
  </div>
}
