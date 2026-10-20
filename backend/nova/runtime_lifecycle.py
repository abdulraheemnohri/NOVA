"""Safe on-demand lifecycle control for NOVA's task-scoped local runtimes.

Only fixed runtime IDs and executable names are accepted. These tools are launched for
one task, bounded by a timeout, and allowed to exit before the result is returned. NOVA
does not keep Whisper, Piper, FFmpeg, or Tesseract resident between tasks.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

RUNTIME_EXECUTABLES: dict[str, frozenset[str]] = {
    "whisper-cpp": frozenset({"whisper-cli"}),
    "piper-tts": frozenset({"piper"}),
    "ffmpeg-audio": frozenset({"ffmpeg"}),
    "tesseract-ocr": frozenset({"tesseract"}),
}
_PROFILE_LIMITS = {"mobile": 1, "balanced": 2, "performance": 3}
_LOCK = threading.RLock()
_ACTIVE: dict[str, int] = {key: 0 for key in RUNTIME_EXECUTABLES}
_RUNS: dict[str, int] = {key: 0 for key in RUNTIME_EXECUTABLES}
_LAST_EXIT: dict[str, int | None] = {key: None for key in RUNTIME_EXECUTABLES}
_LAST_STARTED: dict[str, str | None] = {key: None for key in RUNTIME_EXECUTABLES}
_LAST_FINISHED: dict[str, str | None] = {key: None for key in RUNTIME_EXECUTABLES}
_EVENTS: deque[dict[str, Any]] = deque(maxlen=50)
_SEMAPHORES: dict[int, threading.BoundedSemaphore] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _profile() -> str:
    value = os.environ.get("NOVA_RUNTIME_PROFILE", "balanced").strip().lower()
    return value if value in _PROFILE_LIMITS else "balanced"


def _semaphore(limit: int) -> threading.BoundedSemaphore:
    with _LOCK:
        if limit not in _SEMAPHORES:
            _SEMAPHORES[limit] = threading.BoundedSemaphore(limit)
        return _SEMAPHORES[limit]


def run_task_command(
    runtime_id: str,
    command: Sequence[str],
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    """Run one allowlisted local task command and track its start/stop lifecycle."""
    if runtime_id not in RUNTIME_EXECUTABLES:
        raise ValueError("Runtime ID is not allowlisted.")
    if isinstance(command, (str, bytes)) or not command:
        raise ValueError("Runtime commands must be a non-empty argument sequence.")
    argv = [str(part) for part in command]
    if Path(argv[0]).name not in RUNTIME_EXECUTABLES[runtime_id]:
        raise ValueError("Executable does not match the selected runtime.")
    if kwargs.get("shell", False):
        raise ValueError("Shell execution is forbidden for managed runtimes.")
    kwargs["shell"] = False
    timeout = kwargs.get("timeout")
    if not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > 600:
        raise ValueError("Managed runtime commands require a timeout between 0 and 600 seconds.")
    limit = _PROFILE_LIMITS[_profile()]
    semaphore = _semaphore(limit)
    acquired = semaphore.acquire(timeout=min(float(timeout), 60.0))
    if not acquired:
        raise TimeoutError("NOVA runtime concurrency limit reached; retry after another task finishes.")

    started = _now()
    with _LOCK:
        _ACTIVE[runtime_id] += 1
        _RUNS[runtime_id] += 1
        _LAST_STARTED[runtime_id] = started
        _EVENTS.append({"runtime_id": runtime_id, "event": "started", "at": started})
    exit_code: int | None = None
    try:
        completed = subprocess.run(argv, **kwargs)
        exit_code = int(completed.returncode)
        return completed
    finally:
        finished = _now()
        with _LOCK:
            _ACTIVE[runtime_id] = max(0, _ACTIVE[runtime_id] - 1)
            _LAST_EXIT[runtime_id] = exit_code
            _LAST_FINISHED[runtime_id] = finished
            _EVENTS.append({
                "runtime_id": runtime_id,
                "event": "stopped" if exit_code == 0 else "failed_or_timed_out",
                "at": finished,
                "exit_code": exit_code,
                "duration_seconds": None,
            })
        semaphore.release()


def lifecycle_snapshot() -> dict[str, Any]:
    """Return safe in-memory runtime activity; never expose argv, file paths or input text."""
    profile = _profile()
    with _LOCK:
        runtimes = []
        for runtime_id in RUNTIME_EXECUTABLES:
            active = _ACTIVE[runtime_id]
            runtimes.append({
                "id": runtime_id,
                "state": "running" if active else "stopped",
                "active_jobs": active,
                "runs_since_backend_start": _RUNS[runtime_id],
                "last_exit_code": _LAST_EXIT[runtime_id],
                "last_started_at": _LAST_STARTED[runtime_id],
                "last_finished_at": _LAST_FINISHED[runtime_id],
                "lifecycle": "start on task; stop on completion or timeout",
            })
        events = list(_EVENTS)[-20:]
    return {
        "profile": profile,
        "max_concurrent_managed_tasks": _PROFILE_LIMITS[profile],
        "primary_chat_runtime": "litert-lm",
        "optional_runtimes_resident_when_idle": False,
        "runtimes": runtimes,
        "recent_events": events,
        "policy": "Only registered task executables can be launched. Shell commands and arbitrary process-control requests are rejected. Timeout handling is delegated to subprocess.run; no unrelated process is killed.",
    }
