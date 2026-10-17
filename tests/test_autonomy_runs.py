from nova import autonomy
def test_run_checkpoint_persists_and_updates(tmp_path,monkeypatch):
 from nova.config import settings
 monkeypatch.setattr(settings,"database_path",tmp_path/"runs.sqlite3")
 rid="run-test";created="2026-10-18T00:00:00+00:00"
 autonomy.save_run(rid,"task-test","checkpoints test","running",[],[{"tool":"calculator"}],{"verified":False,"summary":"Pending"},0,created)
 autonomy.save_run(rid,"task-test","checkpoints test","failed",[{"step":1,"tool":"calculator","ok":False,"error":"test"}],[{"tool":"calculator"}],{"verified":False,"summary":"Not verified"},1,created)
 item=autonomy.run_detail(rid)
 assert item["status"]=="failed" and item["current_step"]==1
 assert item["steps"][0]["error"]=="test"
 assert item["plan"][0]["tool"]=="calculator"

def test_plan_preflight_rejects_bad_step_before_execution():
 valid=[{"tool":"calculator","input":{"expression":"2 + 2"},"reason":"calculate"}]
 assert autonomy.validate_steps(valid,4)[0]["tool"]=="calculator"
 invalid=[
  [{"tool":"calculator","input":{"expression":"2 + 2","shell":"rm -rf"} }],
  [{"tool":"calculator","input":{"expression":"1 / 0"}}],
  [{"tool":"knowledge_search","input":{"query":" ","extra":True}}],
  [{"tool":"shell","input":{"command":"echo unsafe"}}],
  [{"tool":"calculator","input":{"expression":"2 + 2"},"reason":"x"*301}],
 ]
 for plan in invalid:
  try:autonomy.validate_steps(plan,4)
  except ValueError:pass
  else:raise AssertionError("invalid plan passed preflight")
def test_plan_preflight_validates_every_step_before_run():
 plan=[
  {"tool":"calculator","input":{"expression":"3 * 7"},"reason":"first"},
  {"tool":"knowledge_search","input":{"query":"local docs"},"reason":"second"},
 ]
 assert len(autonomy.validate_steps(plan,2))==2
 for bad in [[],plan*2]:
  try:autonomy.validate_steps(bad,1)
  except ValueError:pass
  else:raise AssertionError("invalid plan length accepted")
