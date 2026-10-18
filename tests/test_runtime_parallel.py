from __future__ import annotations

import asyncio
import subprocess
import threading
import time

from nova.runtimes import _run_local_command


def test_independent_runtime_commands_can_overlap(monkeypatch) -> None:
    lock = threading.Lock()
    active = 0
    max_active = 0

    def fake_run(command, **kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.08)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(subprocess, "run", fake_run)

    async def run_two() -> None:
        await asyncio.gather(
            _run_local_command(["runtime-a"], capture_output=True, text=True),
            _run_local_command(["runtime-b"], capture_output=True, text=True),
        )

    asyncio.run(run_two())
    assert max_active == 2
