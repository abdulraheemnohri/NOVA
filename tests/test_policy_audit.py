from nova.audit import append_audit, verify_audit
from nova.policy import evaluate_tool

def test_unknown_tool_denied():
    result=evaluate_tool("arbitrary_shell"); assert not result.allowed and not result.requires_approval
def test_write_requires_approval():
    result=evaluate_tool("workspace_write"); assert not result.allowed and result.requires_approval
    assert evaluate_tool("workspace_write",approved=True).allowed
def test_audit_detects_tampering(tmp_path):
    path=tmp_path/"audit.jsonl"; append_audit(path,"one",{"ok":True}); append_audit(path,"two",{"n":2})
    assert verify_audit(path)==(True,2)
    path.write_text(path.read_text().replace('"n":2','"n":3'))
    assert verify_audit(path)[0] is False
