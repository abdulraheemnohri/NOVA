from nova.agent_tools import calculator
def test_calculator_is_not_code_execution():
 assert calculator("(2+3)*4")==20
 for x in ["__import__('os').system('id')","open('/etc/passwd').read()","x+1"]:
  try:calculator(x)
  except (ValueError,SyntaxError):pass
  else:raise AssertionError("unsafe expression accepted")


def test_json_format_tool_is_bounded_and_validates_json(monkeypatch, tmp_path):
 from fastapi import HTTPException
 from nova.config import settings
 from nova.agent_tools import Call, catalog, execute
 monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
 names = {item["name"] for item in catalog()["tools"]}
 assert {"json_format", "base64_encode", "base64_decode"} <= names
 result = execute(Call(name="json_format", input={"json": '{"hello":[1,true]}'}))
 assert result["valid"] is True
 assert '"hello": [' in result["formatted"]
 with pytest.raises(HTTPException) as error:
  execute(Call(name="json_format", input={"json": "{broken"}))
 assert error.value.status_code == 422


def test_base64_tools_roundtrip_utf8_and_reject_invalid_input(monkeypatch, tmp_path):
 import pytest
 from fastapi import HTTPException
 from nova.config import settings
 from nova.agent_tools import Call, execute
 monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
 encoded = execute(Call(name="base64_encode", input={"text": "NOVA ✓"}))["encoded"]
 assert execute(Call(name="base64_decode", input={"encoded": encoded}))["decoded"] == "NOVA ✓"
 with pytest.raises(HTTPException) as error:
  execute(Call(name="base64_decode", input={"encoded": "%%%"}))
 assert error.value.status_code == 422


def test_new_utility_tools_enforce_input_limits(monkeypatch, tmp_path):
 import pytest
 from fastapi import HTTPException
 from nova.config import settings
 from nova.agent_tools import Call, execute
 monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
 for name, payload in [
  ("json_format", {"json": "x" * 100001}),
  ("base64_encode", {"text": "x" * 100001}),
  ("base64_decode", {"encoded": "A" * 140001}),
 ]:
  with pytest.raises(HTTPException) as error:
   execute(Call(name=name, input=payload))
  assert error.value.status_code == 422
