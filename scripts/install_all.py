#!/usr/bin/env python3
"""Cross-platform NOVA dependency installer; installation never starts runtimes."""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".tox", ".nox", "dist", "build", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".next", ".turbo",
}


def discover_requirements(root: Path = ROOT) -> list[Path]:
    """Find project-owned requirements*.txt files without scanning generated trees."""
    found: list[Path] = []
    for directory, child_dirs, filenames in os.walk(root):
        child_dirs[:] = sorted(name for name in child_dirs if name not in EXCLUDED_DIRS)
        for filename in filenames:
            if filename == "requirements.txt" or (
                filename.startswith("requirements") and filename.endswith(".txt")
            ):
                found.append(Path(directory, filename))
    # Core dependencies first, then all other discovered manifests deterministically.
    return sorted(
        set(found),
        key=lambda path: (
            0 if path == root / "requirements.txt" else 1,
            path.relative_to(root).as_posix(),
        ),
    )


def venv_python(root: Path = ROOT, system: str | None = None) -> Path:
    system = system or platform.system()
    return root / ".venv" / ("Scripts/python.exe" if system == "Windows" else "bin/python")


def runtime_install_commands(system: str | None = None) -> list[list[str]]:
    """Commands for maintained OS package managers; these install tools, never launch them."""
    system = system or platform.system()
    if system == "Linux":
        if shutil.which("apt-get"):
            prefix = [] if hasattr(os, "geteuid") and os.geteuid() == 0 else ["sudo"]
            return [
                prefix + ["apt-get", "update"],
                prefix + ["apt-get", "install", "-y", "python3-venv", "python3-dev",
                          "build-essential", "git", "curl", "ca-certificates", "nodejs",
                          "npm", "ffmpeg", "tesseract-ocr"],
            ]
        if shutil.which("dnf"):
            prefix = [] if hasattr(os, "geteuid") and os.geteuid() == 0 else ["sudo"]
            return [prefix + ["dnf", "install", "-y", "python3-devel", "gcc", "gcc-c++",
                              "make", "git", "curl", "nodejs", "npm", "ffmpeg",
                              "tesseract"]]
        if shutil.which("pacman"):
            prefix = [] if hasattr(os, "geteuid") and os.geteuid() == 0 else ["sudo"]
            return [prefix + ["pacman", "-Sy", "--needed", "--noconfirm", "python",
                              "python-pip", "nodejs", "npm", "ffmpeg", "tesseract"]]
        raise RuntimeError("Unsupported Linux package manager. Install Node.js, FFmpeg, and Tesseract manually.")
    if system == "Darwin":
        if not shutil.which("brew"):
            raise RuntimeError("Homebrew is required to install system runtimes on macOS.")
        return [["brew", "install", "node", "ffmpeg", "tesseract"]]
    if system == "Windows":
        if not shutil.which("winget"):
            raise RuntimeError("winget is required to install system runtimes on Windows.")
        common = ["--exact", "--accept-package-agreements", "--accept-source-agreements"]
        return [
            ["winget", "install", "--id", "OpenJS.NodeJS.LTS", *common],
            ["winget", "install", "--id", "Gyan.FFmpeg", *common],
            ["winget", "install", "--id", "UB-Mannheim.TesseractOCR", *common],
        ]
    raise RuntimeError(f"Unsupported operating system: {system}")


def run(command: Sequence[str], *, dry_run: bool) -> None:
    rendered = subprocess.list2cmdline(list(command)) if platform.system() == "Windows" else " ".join(
        shlex.quote(part) for part in command
    )
    print(f"+ {rendered}", flush=True)
    if not dry_run:
        subprocess.run(list(command), cwd=ROOT, check=True)


def install(*, dry_run: bool = False, skip_system_runtimes: bool = False) -> int:
    if sys.version_info < (3, 11):
        print("NOVA requires Python 3.11+. Run this installer with a supported Python.", file=sys.stderr)
        return 2

    manifests = discover_requirements()
    if not manifests:
        print("No requirements*.txt files found.", file=sys.stderr)
        return 2

    if not skip_system_runtimes:
        for command in runtime_install_commands():
            run(command, dry_run=dry_run)

    python = venv_python()
    if not python.exists():
        run([sys.executable, "-m", "venv", str(ROOT / ".venv")], dry_run=dry_run)

    python_command = str(python) if python.exists() else str(venv_python())
    pip_args = [python_command, "-m", "pip", "install", "--upgrade", "pip"]
    run(pip_args, dry_run=dry_run)
    # Install every discovered requirements file, including optional adapters. Pip handles
    # nested -r includes; deterministic order makes the operation reproducible and debuggable.
    run([python_command, "-m", "pip", "install",
         *[argument for path in manifests for argument in ("-r", str(path))]],
        dry_run=dry_run)

    package_json = ROOT / "frontend" / "package.json"
    if package_json.is_file():
        npm = shutil.which("npm")
        if not npm:
            print("npm was not found after runtime setup; reopen the terminal or install Node.js.", file=sys.stderr)
            return 2
        lock = ROOT / "frontend" / "package-lock.json"
        command = [npm, "--prefix", str(ROOT / "frontend"),
                   "ci" if lock.is_file() else "install", "--no-audit", "--no-fund"]
        run(command, dry_run=dry_run)

    if not dry_run:
        (ROOT / "data" / "workspace").mkdir(parents=True, exist_ok=True)
        (ROOT / "data" / "models").mkdir(parents=True, exist_ok=True)
        if not (ROOT / ".env").exists() and (ROOT / ".env.example").exists():
            shutil.copy2(ROOT / ".env.example", ROOT / ".env")
    print(f"Installer complete. Discovered {len(manifests)} requirements file(s).")
    print("Runtime tools are installed but NOT started automatically.")
    print("LiteRT-LM remains the only chat-inference runtime; Whisper.cpp/Piper still need "
          "compatible binaries and local model/voice files.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the installation plan without changing the system")
    parser.add_argument("--skip-system-runtimes", action="store_true",
                        help="install Python/npm dependencies only")
    args = parser.parse_args()
    try:
        return install(dry_run=args.dry_run, skip_system_runtimes=args.skip_system_runtimes)
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"Installation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
