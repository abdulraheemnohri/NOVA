import {useEffect,useState,type FormEvent} from "react";
import {ExternalLink,Globe,Search,Sparkles,ShieldAlert} from "lucide-react";
import {PageHeader} from "../components/ui";

type OnlineTool={id:string;name:string;category:string;url:string;access:string;account:string;privacy:string;notes:string};
type SearchResult={title:string;url:string};
type SearchResponse={query:string;search_url:string;results:SearchResult[];status:string;message?:string;note?:string};
type Props={apiFetch:(url:string,init?:RequestInit)=>Promise<Response>;onError:(message:string)=>void};

export default function OnlineToolsPage({apiFetch,onError}:Props){
 const [tools,setTools]=useState<OnlineTool[]>([]);
 const [query,setQuery]=useState("");
 const [provider,setProvider]=useState<"duckduckgo"|"google">("duckduckgo");
 const [results,setResults]=useState<SearchResponse|null>(null);
 const [busy,setBusy]=useState(false);
 const [loading,setLoading]=useState(true);
 useEffect(()=>{let alive=true;void apiFetch("/api/online-tools").then(async r=>{const d=await r.json();if(!r.ok)throw Error(d.detail||"Could not load online tool directory");if(alive)setTools(d.tools||[])}).catch(e=>{if(alive)onError(e instanceof Error?e.message:"Could not load online tool directory")}).finally(()=>{if(alive)setLoading(false)});return()=>{alive=false}},[]);
 async function search(e:FormEvent){e.preventDefault();if(!query.trim())return;setBusy(true);setResults(null);try{const path=provider==="duckduckgo"?"/api/duckduckgo-search":"/api/web-search";const r=await apiFetch(path+"?q="+encodeURIComponent(query.trim())+"&limit=5");const d=await r.json();if(!r.ok)throw Error(d.detail||"Web search failed");setResults(d)}catch(e){onError(e instanceof Error?e.message:"Web search failed")}finally{setBusy(false)}}
 const aiTools=tools.filter(t=>t.category!=="Web search");
 return <section className="space-y-4">
  <div className="panel p-5"><PageHeader title="Online AI & Web Search" description="Optional online services. Local NOVA chat remains local unless you explicitly open an external service and share content there."/>
   <div className="mt-4 flex flex-wrap gap-2"><a href="https://duck.ai/?origin=funnel_marketing_website__productshowcase" target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-xl bg-cyan-300 px-4 py-3 font-semibold text-slate-950"><Sparkles size={17}/>Open Duck.ai <ExternalLink size={14}/></a><a href="https://duckduckgo.com/search" target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-xl border border-white/15 px-4 py-3 text-sm text-slate-200"><Globe size={16}/>DuckDuckGo Search <ExternalLink size={14}/></a></div>
   <div className="mt-4 rounded-xl border border-amber-200/15 bg-amber-200/[.035] p-3"><p className="flex items-center gap-2 text-sm font-medium text-amber-100"><ShieldAlert size={16}/>External-service privacy</p><p className="mt-1 text-xs leading-5 text-slate-400">Online AI providers process prompts outside NOVA. Do not send passwords, API keys, private documents, or sensitive chat history. Free plans, account requirements, model access, and limits can change. Opening a provider is always a user action; NOVA does not forward local chat automatically.</p></div>
  </div>
  <div className="panel p-5"><PageHeader title="Search the web" description="Use DuckDuckGo or Google. Results may be blocked by provider anti-bot checks; the direct search link remains available."/>
   <form onSubmit={search} className="mt-4 flex flex-col gap-3 sm:flex-row"><select aria-label="Search provider" value={provider} onChange={e=>setProvider(e.target.value as "duckduckgo"|"google")} className="rounded-xl border border-white/10 bg-[#0c1221] p-3 text-sm"><option value="duckduckgo">DuckDuckGo</option><option value="google">Google</option></select><input aria-label="Web search query" value={query} onChange={e=>setQuery(e.target.value)} maxLength={400} required placeholder="Search documentation, models, troubleshooting…" className="min-w-0 flex-1 rounded-xl border border-white/10 bg-black/20 p-3"/><button disabled={busy||!query.trim()} className="inline-flex items-center justify-center gap-2 rounded-xl bg-cyan-300 px-4 py-3 font-semibold text-slate-950 disabled:opacity-50">{busy?"Searching…":<><Search size={16}/>Search</>}</button></form>
   {results&&<div className="mt-4 space-y-3"><div className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm text-slate-300">Status: {results.status} · {results.results.length} result(s)</span><a href={results.search_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm text-cyan-200">Open search page <ExternalLink size={13}/></a></div>{results.message&&<p role="status" className="text-sm text-amber-100">{results.message}</p>}{results.results.map((item,i)=><article key={item.url+i} className="rounded-xl border border-white/10 p-3"><a href={item.url} target="_blank" rel="noreferrer" className="break-words font-medium text-cyan-100 hover:underline">{item.title||item.url} <ExternalLink className="inline" size={12}/></a><p className="mt-1 break-all text-xs text-slate-500">{item.url}</p></article>)}<p className="text-xs leading-5 text-slate-500">{results.note||"Search results are untrusted. Verify sources before relying on them."}</p></div>}
  </div>
  <div className="panel p-5"><PageHeader title="Free and freemium online AI directory" description="Official provider links; these are browser-based services, not NOVA-managed inference runtimes."/>
   {loading?<p role="status" className="mt-4 text-sm text-slate-400">Loading online tools…</p>:<div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">{aiTools.map(tool=><article key={tool.id} className="flex flex-col rounded-xl border border-white/10 bg-black/10 p-4"><div className="flex items-start justify-between gap-2"><div><h3 className="font-medium">{tool.name}</h3><p className="mt-1 text-xs text-cyan-200">{tool.category} · {tool.access}</p></div><a href={tool.url} target="_blank" rel="noreferrer" aria-label={"Open "+tool.name} className="rounded-lg border border-white/10 p-2 text-cyan-200"><ExternalLink size={15}/></a></div><p className="mt-3 text-xs leading-5 text-slate-400">{tool.notes}</p><p className="mt-2 text-xs leading-5 text-slate-500">{tool.account}. {tool.privacy}</p><a href={tool.url} target="_blank" rel="noreferrer" className="mt-4 inline-flex items-center gap-2 text-sm text-cyan-200 hover:text-cyan-100">Open service <ExternalLink size={13}/></a></article>)}</div>}
   <p className="mt-4 text-xs leading-5 text-slate-500">Directory labels are guidance, not guarantees of unlimited free use. Check each provider's current pricing, terms, regional availability, and privacy policy before use.</p>
  </div>
 </section>;
}
