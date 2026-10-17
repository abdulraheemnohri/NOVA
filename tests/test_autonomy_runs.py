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
