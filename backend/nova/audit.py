"""Hash-chained JSONL audit log with fail-closed integrity checks.

The chain is tamper-evident, not immutable against a privileged administrator.
"""
import hashlib
import hmac
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_ZERO_HASH = "0" * 64


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _verify_unlocked(path: Path) -> tuple[bool, int, str]:
    if not path.exists():
        return True, 0, _ZERO_HASH
    previous, count = _ZERO_HASH, 0
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    return False, count, previous
                claimed = record.pop("hash", None)
                if not isinstance(claimed, str) or len(claimed) != 64:
                    return False, count, previous
                if record.get("previous_hash") != previous:
                    return False, count, previous
                actual = hashlib.sha256(_canonical(record)).hexdigest()
                if not hmac.compare_digest(actual, claimed):
                    return False, count, previous
                previous, count = claimed, count + 1
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False, count, previous
    return True, count, previous


def append_audit(path: Path, event_type: str, details: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        valid, _, previous = _verify_unlocked(path)
        if not valid:
            raise ValueError("Audit chain integrity check failed; refusing to append.")
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "details": details,
            "previous_hash": previous,
        }
        event["hash"] = hashlib.sha256(_canonical(event)).hexdigest()
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
        return event


def verify_audit(path: Path) -> tuple[bool, int]:
    with _lock:
        valid, count, _ = _verify_unlocked(path)
        return valid, count
