from __future__ import annotations

import subprocess

import pytest

from nova import runtime_lifecycle as lifecycle


def test_task_runtime_starts_and_returns_to_stopped(monkeypatch):
    lifecycle._ACTIVE["whisper-cpp"] = 0
    monkeypatch.setattr(
        lifecycle.subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, stdout="ok", stderr=""),
    )
    result = lifecycle.run_task_command(
        "whisper-cpp",
        ["/usr/bin/whisper-cli", "--help"],
        timeout=5,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    status = lifecycle.lifecycle_snapshot()
    runtime = next(item for item in status["runtimes"] if item["id"] == "whisper-cpp")
    assert runtime["state"] == "stopped"
    assert runtime["active_jobs"] == 0
    assert runtime["runs_since_backend_start"] >= 1


def test_task_runtime_rejects_unknown_executable(monkeypatch):
    called = False

    def fake_run(*args, **kwargs):
        nonlocal called
        called = True
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr(lifecycle.subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="does not match"):
        lifecycle.run_task_command("whisper-cpp", ["/tmp/arbitrary", "--help"], timeout=5)
    assert called is False


def test_task_runtime_rejects_shell_and_unbounded_timeout():
    with pytest.raises(ValueError, match="Shell execution"):
        lifecycle.run_task_command(
            "whisper-cpp", ["whisper-cli", "--help"], timeout=5, shell=True
        )
    with pytest.raises(ValueError, match="timeout"):
        lifecycle.run_task_command(
            "whisper-cpp", ["whisper-cli", "--help"], timeout=9999
        )


def test_mobile_profile_serializes_managed_tasks(monkeypatch):
    monkeypatch.setenv("NOVA_RUNTIME_PROFILE", "mobile")
    assert lifecycle.lifecycle_snapshot()["max_concurrent_managed_tasks"] == 1
