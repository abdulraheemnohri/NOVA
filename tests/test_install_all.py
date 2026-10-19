from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.install_all import discover_requirements, runtime_install_commands


def test_discover_requirements_is_recursive_deterministic_and_skips_generated_dirs(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("-r requirements.txt\n", encoding="utf-8")
    nested = tmp_path / "backend" / "requirements-extra.txt"
    nested.parent.mkdir()
    nested.write_text("example-package\n", encoding="utf-8")
    ignored = tmp_path / ".venv" / "requirements-hidden.txt"
    ignored.parent.mkdir()
    ignored.write_text("should-not-install\n", encoding="utf-8")
    node_ignored = tmp_path / "frontend" / "node_modules" / "x" / "requirements.txt"
    node_ignored.parent.mkdir(parents=True)
    node_ignored.write_text("should-not-install\n", encoding="utf-8")

    found = discover_requirements(tmp_path)

    assert found == [
        tmp_path / "requirements.txt",
        tmp_path / "backend" / "requirements-extra.txt",
        tmp_path / "requirements-dev.txt",
    ]


def test_windows_runtime_setup_installs_tools_without_starting_them() -> None:
    with patch("scripts.install_all.shutil.which", return_value="C:/Windows/System32/winget.exe"):
        commands = runtime_install_commands("Windows")

    assert len(commands) == 5
    assert all(command[0] == "winget" and command[1] == "install" for command in commands)
    assert any("OpenJS.NodeJS.LTS" in command for command in commands)
    assert any("Gyan.FFmpeg" in command for command in commands)
    assert any("UB-Mannheim.TesseractOCR" in command for command in commands)


def test_linux_apt_setup_includes_audio_and_ocr_tools() -> None:
    with patch("scripts.install_all.shutil.which", side_effect=lambda name: "/usr/bin/apt-get" if name == "apt-get" else None), \
         patch("scripts.install_all.os.geteuid", return_value=0, create=True):
        commands = runtime_install_commands("Linux")

    assert commands[0] == ["apt-get", "update"]
    install_command = commands[1]
    assert "ffmpeg" in install_command
    assert "tesseract-ocr" in install_command
    assert "nodejs" in install_command
    assert "npm" in install_command



def test_litert_lm_is_installed_by_default_and_can_be_skipped(monkeypatch) -> None:
    import sys
    import scripts.install_all as installer

    captured = []

    def fake_install(**kwargs):
        captured.append(kwargs)
        return 0

    monkeypatch.setattr(installer, "install", fake_install)
    monkeypatch.setattr(sys, "argv", ["install_all.py"])
    assert installer.main() == 0
    assert captured[-1]["install_litert_lm"] is True

    monkeypatch.setattr(sys, "argv", ["install_all.py", "--skip-litert-lm"])
    assert installer.main() == 0
    assert captured[-1]["install_litert_lm"] is False


def test_dry_run_and_skip_system_runtimes_are_forwarded(monkeypatch) -> None:
    import sys
    import scripts.install_all as installer

    captured = []

    def fake_install(**kwargs):
        captured.append(kwargs)
        return 0

    monkeypatch.setattr(installer, "install", fake_install)
    monkeypatch.setattr(sys, "argv", ["install_all.py", "--dry-run", "--skip-system-runtimes"])
    assert installer.main() == 0
    assert captured[-1]["dry_run"] is True
    assert captured[-1]["skip_system_runtimes"] is True



def test_installer_cli_forwards_dry_run_and_skip_system_runtime_flags(monkeypatch) -> None:
    import sys
    import scripts.install_all as installer

    captured = []

    def fake_install(**kwargs):
        captured.append(kwargs)
        return 0

    monkeypatch.setattr(installer, "install", fake_install)
    monkeypatch.setattr(sys, "argv", ["install_all.py", "--dry-run", "--skip-system-runtimes"])
    assert installer.main() == 0
    assert captured[-1]["dry_run"] is True
    assert captured[-1]["skip_system_runtimes"] is True
    assert "install_litert_lm" not in captured[-1]
