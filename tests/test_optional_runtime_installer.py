from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts import install_optional_runtimes as installer


def test_litert_and_piper_install_is_opt_in_and_never_starts_a_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(installer, "VENV_PYTHON", tmp_path / "bin" / "python")
    installer.VENV_PYTHON.parent.mkdir(parents=True, exist_ok=True)
    installer.VENV_PYTHON.touch()
    commands: list[list[str]] = []
    monkeypatch.setattr(installer, "run", lambda command, **kwargs: commands.append(command))

    result = installer.install_selected(
        litert_lm=True, piper=True, whisper_cpp=False, whisper_tag=None, jobs=2, dry_run=False
    )

    assert result == 0
    assert commands == [[
        str(installer.VENV_PYTHON), "-m", "pip", "install", "--upgrade",
        "litert-lm>=0.18,<1", "piper-tts>=1.2,<2",
    ]]
    assert not any("run" in command for command in commands)


def test_whisper_build_requires_an_explicit_pinned_tag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(installer, "VENV_PYTHON", tmp_path / "python")
    monkeypatch.setattr(installer, "WHISPER_SOURCE", tmp_path / "tools" / "whisper.cpp")

    result = installer.install_selected(
        litert_lm=False, piper=False, whisper_cpp=True, whisper_tag=None, jobs=2, dry_run=True
    )

    assert result == 2


def test_whisper_build_dry_run_uses_explicit_tag_and_does_not_clone(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(installer, "VENV_PYTHON", tmp_path / "python")
    monkeypatch.setattr(installer, "WHISPER_SOURCE", tmp_path / "tools" / "whisper.cpp")
    monkeypatch.setattr(installer.shutil, "which", lambda name: f"/usr/bin/{name}")
    commands: list[list[str]] = []
    monkeypatch.setattr(installer, "run", lambda command, **kwargs: commands.append(command))

    result = installer.install_selected(
        litert_lm=False, piper=False, whisper_cpp=True, whisper_tag="v1.7.6", jobs=2, dry_run=True
    )

    assert result == 0
    assert commands[0][1:5] == ["clone", "--depth", "1", "--branch"]
    assert "v1.7.6" in commands[0]
    assert all("cmake" in command[0] for command in commands[1:])
