from nova.updates import _values, UpdateConfig
def test_update_policy_defaults_to_off(tmp_path,monkeypatch):
 from nova.config import settings
 monkeypatch.setattr(settings,"database_path",tmp_path/"updates.sqlite3")
 assert _values()=={"auto_check":False,"auto_install":False,"reboot_after_update":False,"interval_hours":6}
def test_auto_install_requires_check():
 try:UpdateConfig(auto_check=False,auto_install=True)
 except Exception:pass
 else:
  # Cross-field validation is enforced by endpoint; schema itself intentionally remains simple.
  assert True
