import pytest
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


def test_csv_summary_reports_bounded_column_statistics(monkeypatch, tmp_path):
 from nova.config import settings
 from nova.agent_tools import Call, catalog, execute
 monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
 names = {item["name"] for item in catalog()["tools"]}
 assert {"csv_summary", "markdown_outline"} <= names
 result = execute(Call(name="csv_summary", input={"csv": "name,age,active\\nA,20,true\\nB,,false\\n"}))
 assert result["row_count"] == 2
 assert result["column_count"] == 3
 assert result["columns"][0] == {"name": "name", "non_empty": 2, "missing": 0, "inferred_type": "text"}
 assert result["columns"][1]["inferred_type"] == "number"
 assert result["columns"][1]["missing"] == 1
 assert result["columns"][2]["inferred_type"] == "boolean"


def test_csv_summary_rejects_duplicate_headers_and_oversized_data(monkeypatch, tmp_path):
 from fastapi import HTTPException
 from nova.config import settings
 from nova.agent_tools import Call, execute
 monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
 for value in ["x,x\\n1,2\\n", "x\\n" + ("a\\n" * 2001)]:
  with pytest.raises(HTTPException) as error:
   execute(Call(name="csv_summary", input={"csv": value}))
  assert error.value.status_code == 422


def test_markdown_outline_extracts_heading_levels_and_lines(monkeypatch, tmp_path):
 from nova.config import settings
 from nova.agent_tools import Call, execute
 monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
 result = execute(Call(name="markdown_outline", input={"markdown": "# Title\\ntext\\n### Details ###\\n"}))
 assert result["heading_count"] == 2
 assert result["headings"] == [
  {"level": 1, "text": "Title", "line": 1},
  {"level": 3, "text": "Details", "line": 3},
