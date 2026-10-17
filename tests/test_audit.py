import json

import pytest

from nova.audit import append_audit, verify_audit


def test_audit_chain_round_trip(tmp_path):
    path = tmp_path / "audit.jsonl"
    append_audit(path, "test.one", {"value": 1})
    append_audit(path, "test.two", {"value": 2})
    assert verify_audit(path) == (True, 2)


def test_audit_tampering_is_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    append_audit(path, "test.event", {"value": "original"})
    record = json.loads(path.read_text(encoding="utf-8"))
    record["details"]["value"] = "tampered"
    path.write_text(json.dumps(record) + "\\n", encoding="utf-8")
    assert verify_audit(path) == (False, 0)


def test_malformed_audit_log_fails_closed(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text('{"broken":\n', encoding="utf-8")
    assert verify_audit(path) == (False, 0)
    with pytest.raises(ValueError, match="integrity check failed"):
        append_audit(path, "must.not.append", {})
