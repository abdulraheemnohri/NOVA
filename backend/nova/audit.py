"""Hash-chained JSONL audit log. Tamper-evident, not administrator-proof immutable."""
import hashlib, json, threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
_lock = threading.Lock()

def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

def append_audit(path: Path, event_type: str, details: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        previous = "0" * 64
        if path.exists():
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    if line.strip(): previous = json.loads(line)["hash"]
        event = {"timestamp": datetime.now(timezone.utc).isoformat(), "event_type": event_type,
                 "details": details, "previous_hash": previous}
        event["hash"] = hashlib.sha256(_canonical(event)).hexdigest()
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            stream.flush()
        return event

def verify_audit(path: Path) -> tuple[bool, int]:
    if not path.exists(): return True, 0
    previous, count = "0" * 64, 0
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip(): continue
            record = json.loads(line); claimed = record.pop("hash", None)
            if record.get("previous_hash") != previous: return False, count
            if hashlib.sha256(_canonical(record)).hexdigest() != claimed: return False, count
            previous, count = claimed, count + 1
    return True, count
