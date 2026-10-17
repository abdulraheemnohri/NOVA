"""Opt-in GitHub updater with clean-tree checks, test-before-reboot, and rollback."""
from __future__ import annotations
import json, os, platform, shutil, sqlite3, subprocess, sys, threading, time, urllib.request
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from nova.config import settings
from nova.audit import append_audit
router=APIRouter(prefix="/api/updates",tags=["updates"])
REPO="abdulraheemnohri/NOVA"
ROOT=Path(__file__).resolve().parents[2]
_LOCK=threading.Lock()
_STOP=threading.Event()
_THREAD=None
class UpdateConfig(BaseModel):
 model_config=ConfigDict(extra="forbid")
 auto_check:bool=False
 auto_install:bool=False
 reboot_after_update:bool=False
 interval_hours:int=Field(default=6,ge=1,le=24)
def _db():
 settings.database_path.parent.mkdir(parents=True,exist_ok=True);c=sqlite3.connect(settings.database_path,timeout=10);c.row_factory=sqlite3.Row
 c.execute("CREATE TABLE IF NOT EXISTS nova_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL)");return c
def _values():
 c=_db()
 try:r={x["key"]:x["value"] for x in c.execute("SELECT key,value FROM nova_settings WHERE key LIKE 'update_%'").fetchall()}
 finally:c.close()
 try:hours=max(1,min(24,int(r.get("update_interval_hours","6"))))
 except ValueError:hours=6
 return {"auto_check":r.get("update_auto_check","false")=="true","auto_install":r.get("update_auto_install","false")=="true","reboot_after_update":r.get("update_reboot","false")=="true","interval_hours":hours}
def _git(*args,timeout=30):
 p=subprocess.run(["git","-C",str(ROOT),*args],capture_output=True,text=True,timeout=timeout)
 if p.returncode:raise RuntimeError((p.stderr or p.stdout or "git command failed").strip()[-1000:])
 return p.stdout.strip()
def _guard():
 if _git("rev-parse","--is-inside-work-tree")!="true":raise RuntimeError("NOVA installation is not a Git working tree.")
 branch=_git("branch","--show-current")
 if branch!="main":raise RuntimeError(f"Updates require the main branch; current branch is {branch!r}.")
 remote=_git("remote","get-url","origin").rstrip("/")
 if remote not in {f"https://github.com/{REPO}",f"https://github.com/{REPO}.git",f"git@github.com:{REPO}.git"}:raise RuntimeError("origin does not match the trusted NOVA GitHub repository.")
 if _git("status","--porcelain"):raise RuntimeError("Working tree has local changes; commit or back them up before updating.")
 return _git("rev-parse","HEAD")
def _remote_sha():
 req=urllib.request.Request(f"https://api.github.com/repos/{REPO}/commits/main",headers={"Accept":"application/vnd.github+json","User-Agent":"NOVA-updater"})
 with urllib.request.urlopen(req,timeout=12) as response:data=json.loads(response.read(1_000_000))
 sha=data.get("sha")
 if not isinstance(sha,str) or len(sha)!=40:raise RuntimeError("GitHub returned an invalid commit SHA.")
 return sha
def check():
 current=_git("rev-parse","HEAD")
 remote=_remote_sha()
 return {"repository":REPO,"branch":"main","current_sha":current,"latest_sha":remote,"update_available":current!=remote,"checked_at":datetime.now(timezone.utc).isoformat(),"automatic_updates_enabled":_values()["auto_install"]}
def _tests():
 subprocess.run([sys.executable,"-m","pytest","-q"],cwd=ROOT,check=True,timeout=300)
 front=ROOT/"frontend"
 if (front/"package-lock.json").is_file():
  npm=shutil.which("npm")
  if not npm:raise RuntimeError("npm is required to validate this update.")
  subprocess.run([npm,"ci","--no-audit","--no-fund"],cwd=front,check=True,timeout=600)
  subprocess.run([npm,"test"],cwd=front,check=True,timeout=300)
  subprocess.run([npm,"run","build"],cwd=front,check=True,timeout=300)
def _reboot():
 if platform.system()!="Linux":raise RuntimeError("Automatic reboot is supported only on Linux hosts.")
 if not shutil.which("systemctl"):raise RuntimeError("systemctl is not installed; update installed but reboot was not requested.")
 if hasattr(os,"geteuid") and os.geteuid()!=0:raise RuntimeError("Reboot requires a privileged service account; no privilege escalation is attempted.")
 subprocess.run(["systemctl","reboot"],check=True,timeout=8)
def install(automatic=False):
 if not _LOCK.acquire(blocking=False):raise HTTPException(409,"An update is already running.")
 previous=None
 try:
  previous=_guard()
  latest=_remote_sha()
  if latest==previous:return {"updated":False,"reason":"already_current","current_sha":previous}
  _git("fetch","--ff-only","origin","main",timeout=120)
  target=_git("rev-parse","FETCH_HEAD")
  if target!=latest:raise RuntimeError("Fetched commit did not match the verified GitHub API SHA.")
  _git("merge","--ff-only","FETCH_HEAD",timeout=120)
  try:_tests()
  except Exception:
   _git("reset","--hard",previous,timeout=30)
   append_audit(settings.audit_path,"update.rolled_back",{"from":previous,"rejected":target})
   raise RuntimeError("Updated code failed validation; the checkout was rolled back to its previous commit.")
  append_audit(settings.audit_path,"update.installed",{"previous":previous,"current":target,"automatic":automatic})
  cfg=_values()
  reboot_requested=bool(cfg["reboot_after_update"])
  if reboot_requested:
   try:_reboot()
   except Exception as e:
    append_audit(settings.audit_path,"update.reboot_failed",{"error":type(e).__name__})
    return {"updated":True,"previous_sha":previous,"current_sha":target,"tests":"passed","reboot_requested":False,"restart_required":True,"reboot_error":str(e)[:300]}
  return {"updated":True,"previous_sha":previous,"current_sha":target,"tests":"passed","reboot_requested":reboot_requested,"restart_required":not reboot_requested}
 except HTTPException:raise
 except Exception as e:
  append_audit(settings.audit_path,"update.failed",{"error":type(e).__name__})
  raise HTTPException(409,str(e)[:1000]) from e
 finally:_LOCK.release()
@router.get("/settings")
def read_settings():return _values()
@router.put("/settings")
def write_settings(req:UpdateConfig):
 if req.auto_install and not req.auto_check:raise HTTPException(422,"Automatic installation requires automatic update checks.")
 if req.reboot_after_update and not req.auto_install:raise HTTPException(422,"Automatic reboot requires automatic installation.")
 c=_db();now=datetime.now(timezone.utc).isoformat()
 try:
  c.executemany("INSERT INTO nova_settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",[
   ("update_auto_check",str(req.auto_check).lower(),now),("update_auto_install",str(req.auto_install).lower(),now),("update_reboot",str(req.reboot_after_update).lower(),now),("update_interval_hours",str(req.interval_hours),now)]);c.commit()
 finally:c.close()
 append_audit(settings.audit_path,"update.settings.changed",req.model_dump());return _values()
@router.get("/check")
def check_route():
 try:return check()
 except Exception as e:raise HTTPException(503,str(e)[:500]) from e
@router.post("/install")
def install_route():return install(automatic=False)
def _worker():
 while not _STOP.wait(60):
  cfg=_values()
  if not cfg["auto_check"]:continue
  try:
   status=check()
   if cfg["auto_install"] and status["update_available"]:install(automatic=True)
  except Exception as e:append_audit(settings.audit_path,"update.background_check_failed",{"error":type(e).__name__})
  # After a successful pass, wait the configured interval before checking again.
  if _STOP.wait(max(60,cfg["interval_hours"]*3600-60)):return
def start_worker():
 global _THREAD
 if _THREAD and _THREAD.is_alive():return
 _STOP.clear();_THREAD=threading.Thread(target=_worker,name="nova-github-updater",daemon=True);_THREAD.start()
def stop_worker():
 _STOP.set()
