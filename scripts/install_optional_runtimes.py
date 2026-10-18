"""Install selected optional local runtimes into NOVA's isolated environment.

This script installs packages/tools only. It never starts a model server, downloads
model weights/voices, or changes NOVA's chat provider. LiteRT-LM is the only chat
runtime and can be installed with --litert-lm; a model and server configuration
must still be selected explicitly.
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
WHISPER_SOURCE = ROOT / "tools" / "whisper.cpp"


def run(command: list[str], *, dry_run: bool = False, cwd: Path = ROOT) -> None:
    print("+ " + subprocess.list2cmdline(command) if os.name == "nt" else "+ " + " ".join(command), flush=True)
    if not dry_run:
        subprocess.run(command, cwd=cwd, check=True)


def install_selected(*, litert_lm: bool, piper: bool, whisper_cpp: bool,
                     whisper_tag: str | None, dry_run: bool) -> int:
    if not VENV_PYTHON.is_file() and not dry_run:
        print("Create NOVA's virtual environment first: python scripts/install_all.py", file=sys.stderr)
        return 2
    python = str(VENV_PYTHON)
    selected = litert_lm or piper or whisper_cpp
    if not selected:
        print("Select at least one runtime: --litert-lm, --piper, or --whisper-cpp.", file=sys.stderr)
        return 2

    packages: list[str] = []
    if litert_lm:
        packages.append("litert-lm")
    if piper:
        packages.append("piper-tts")
    if packages:
        run([python, "-m", "pip", "install", "--upgrade", *packages], dry_run=dry_run)

    if whisper_cpp:
        if not whisper_tag:
            print("--whisper-cpp requires an explicit --whisper-tag release to pin the source version.", file=sys.stderr)
            return 2
        git = shutil.which("git")
        cmake = shutil.which("cmake")
        if not git or not cmake:
            print("Building whisper.cpp requires Git, CMake, and a compatible C/C++ compiler.", file=sys.stderr)
            return 2
        if WHISPER_SOURCE.exists() and not (WHISPER_SOURCE / ".git").is_dir():
            print(f"Refusing to overwrite non-Git path: {WHISPER_SOURCE}", file=sys.stderr)
            return 2
        if not WHISPER_SOURCE.exists():
            run([git, "clone", "--depth", "1", "--branch", whisper_tag,
                 "https://github.com/ggml-org/whisper.cpp.git", str(WHISPER_SOURCE)],
                dry_run=dry_run)
        else:
            run([git, "fetch", "--depth", "1", "origin", "tag", whisper_tag], dry_run=dry_run,
                cwd=WHISPER_SOURCE)
            run([git, "checkout", "--detach", whisper_tag], dry_run=dry_run, cwd=WHISPER_SOURCE)
        build = WHISPER_SOURCE / "build"
        run([cmake, "-S", str(WHISPER_SOURCE), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release"],
            dry_run=dry_run)
        run([cmake, "--build", str(build), "--config", "Release", "--parallel"],
            dry_run=dry_run)
        print("whisper.cpp source build complete. Configure NOVA_WHISPER_CLI_PATH to the built CLI.")
        print("Download a compatible GGML model separately and configure NOVA_WHISPER_MODEL_PATH.")

    if litert_lm:
        print(f"LiteRT-LM installed into NOVA's environment. CLI path: {VENV_PYTHON.parent / ('litert-lm.exe' if os.name == 'nt' else 'litert-lm')}")
        print("Choose a compatible local/.litertlm model and explicitly configure its supported serving mode.")
        print("NOVA will not start the service or download model weights automatically.")
    if piper:
        print("Piper installed into NOVA's environment. Configure NOVA_PIPER_CLI_PATH and provide a voice .onnx plus .onnx.json sidecar.")
        print("Voice files are not downloaded automatically.")
    if dry_run:
        print("Dry run: no packages installed and no source checked out.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--litert-lm", action="store_true", help="install the official LiteRT-LM CLI package")
    parser.add_argument("--piper", action="store_true", help="install Piper TTS into NOVA's virtual environment")
    parser.add_argument("--whisper-cpp", action="store_true", help="build whisper.cpp from its upstream Git repository")
    parser.add_argument("--whisper-tag", help="explicit upstream whisper.cpp release tag to build (required with --whisper-cpp)")
    parser.add_argument("--dry-run", action="store_true", help="print commands without changing files or installing packages")
    args = parser.parse_args()
    try:
        return install_selected(litert_lm=args.litert_lm, piper=args.piper,
                                whisper_cpp=args.whisper_cpp, whisper_tag=args.whisper_tag,
                                dry_run=args.dry_run)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Optional runtime installation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
