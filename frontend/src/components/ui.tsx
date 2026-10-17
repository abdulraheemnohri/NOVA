import type { ReactNode, ButtonHTMLAttributes, InputHTMLAttributes } from "react";
import { LoaderCircle, type LucideIcon } from "lucide-react";

export function Panel({children,className=""}:{children:ReactNode;className?:string}) {
  return <section className={`panel ${className}`}>{children}</section>;
}

export function PageHeader({eyebrow,title,description,actions}:{eyebrow?:string;title:string;description?:string;actions?:ReactNode}) {
  return <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
    <div>{eyebrow&&<p className="mb-1 text-xs font-semibold uppercase tracking-[.18em] text-cyan-300">{eyebrow}</p>}<h2 className="text-xl font-semibold tracking-tight">{title}</h2>{description&&<p className="mt-1 max-w-3xl text-sm leading-6 text-slate-400">{description}</p>}</div>
    {actions&&<div className="flex flex-wrap gap-2">{actions}</div>}
  </div>;
}

export function StatusBadge({status,tone="neutral"}:{status:string;tone?:"good"|"warn"|"danger"|"info"|"neutral"}) {
  const tones={good:"border-emerald-300/20 bg-emerald-300/10 text-emerald-200",warn:"border-amber-300/20 bg-amber-300/10 text-amber-200",danger:"border-rose-300/20 bg-rose-300/10 text-rose-200",info:"border-cyan-300/20 bg-cyan-300/10 text-cyan-100",neutral:"border-white/10 bg-white/[.04] text-slate-300"};
  return <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium ${tones[tone]}`}>{status}</span>;
}

export function EmptyState({icon:Icon,title,description,action}:{icon?:LucideIcon;title:string;description?:string;action?:ReactNode}) {
  return <div className="flex min-h-36 flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 px-5 py-8 text-center">
    {Icon&&<span className="mb-3 rounded-xl border border-white/10 bg-white/[.03] p-3 text-slate-400"><Icon size={20}/></span>}
    <h3 className="text-sm font-semibold text-slate-200">{title}</h3>{description&&<p className="mt-1 max-w-md text-sm leading-6 text-slate-500">{description}</p>}{action&&<div className="mt-4">{action}</div>}
  </div>;
}

export function MetricCard({icon,title,value,detail,tone="cyan"}:{icon:ReactNode;title:string;value:string;detail:string;tone?:"cyan"|"green"|"amber"|"violet"}) {
  const tones={cyan:"text-cyan-300",green:"text-emerald-300",amber:"text-amber-200",violet:"text-violet-300"};
  return <article className="panel min-w-0 p-5"><div className={`mb-4 inline-flex rounded-xl border border-white/5 bg-white/[.025] p-2.5 ${tones[tone]}`}>{icon}</div><p className="text-sm text-slate-400">{title}</p><p className="mt-1 break-words text-xl font-semibold tracking-tight">{value}</p><p className="mt-2 text-xs leading-5 text-slate-500">{detail}</p></article>;
}

export function SettingRow({label,value,description}:{label:string;value:string;description?:string}) {
  return <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/5 py-3 last:border-b-0"><div><span className="text-sm text-slate-300">{label}</span>{description&&<p className="mt-1 text-xs text-slate-500">{description}</p>}</div><span className="max-w-full break-all text-right text-sm text-slate-100">{value}</span></div>;
}

export function ActionButton({children,loading=false,variant="primary",...props}:ButtonHTMLAttributes<HTMLButtonElement>&{loading?:boolean;variant?:"primary"|"secondary"|"danger"}) {
  const variants={primary:"bg-cyan-300 text-slate-950 hover:bg-cyan-200",secondary:"border border-white/10 bg-white/[.025] text-slate-200 hover:bg-white/[.06]",danger:"border border-rose-300/20 bg-rose-300/10 text-rose-100 hover:bg-rose-300/15"};
  return <button {...props} disabled={loading||props.disabled} className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${props.className||""}`}>{loading&&<LoaderCircle size={15} className="animate-spin"/>}{children}</button>;
}

export function SearchField(props:InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`min-w-0 w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2.5 text-sm placeholder:text-slate-600 focus:border-cyan-200/50 focus:outline-none focus:ring-2 focus:ring-cyan-200/10 ${props.className||""}`}/>;
}
