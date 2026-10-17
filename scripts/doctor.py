#!/usr/bin/env python3
"""Read-only NOVA environment diagnostics. Does not print secrets or mutate files."""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_MODULES = ("fastapi", "uvicorn", "pydantic", "pydantic_settings", "multipart")
OPTIONAL_COMMANDS = ("litert-lm", "whisper-cli", "whisper.cpp", "piper", "llama-server")


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\\"").strip("'")
    return values


def main() -> int:
    env = read_env_file(ROOT / ".env")
    env.update({key: value for key, value in os.environ.items() if key.startswith("NOVA_")})
    failures = 0
    print("NOVA environment doctor (read-only)")
    print(f"Repository: {ROOT}")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    if sys.version_info < (3, 11):
        print("FAIL Python 3.11 or newer is required")
        failures += 1
    else:
        print("OK Python version")

    for module in REQUIRED_MODULES:
        if importlib.util.find_spec(module):
            print(f"OK Python dependency: {module}")
        else:
            print(f"FAIL missing Python dependency: {module}")
            failures += 1

    frontend = ROOT / "frontend"
    if (frontend / "package.json").is_file():
        print("OK frontend package manifest")
    else:
        print("WARN frontend/package.json is missing")

    if (ROOT / ".env").is_file():
        print("OK .env exists (values hidden)")
    else:
        print("WARN .env is missing; copy .env.example to .env before first run")

    for name in ("NOVA_WORKSPACE", "NOVA_DATABASE_PATH", "NOVA_AUDIT_PATH"):
        configured = env.get(name)
        if configured:
            path = Path(configured).expanduser()
            if not path.is_absolute():
                path = ROOT / path
            print(f"INFO {name}: {'exists' if path.exists() else 'not created yet'}")
        else:
            print(f"INFO {name}: using application default")

    for command in OPTIONAL_COMMANDS:
        resolved = shutil.which(command)
        if resolved:
            print(f"OK optional command {command}: {resolved}")
        else:
            print(f"INFO optional command {command}: not found (may be unused)")

    base_url = env.get("NOVA_LITERT_BASE_URL", "http://127.0.0.1:9379/v1").rstrip("/")
    if not base_url.startswith(("http://127.0.0.1", "http://localhost", "http://[::1]")):
        print("WARN LiteRT endpoint is not an obvious loopback URL; check local-only policy")
    try:
        req = urllib.request.Request(base_url + "/models", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as response:
            print(f"OK LiteRT endpoint reachable: HTTP {response.status} (model correctness not verified)")
    except (urllib.error.URLError, TimeoutError, OSError):
        print(f"WARN LiteRT endpoint not reachable at {base_url} (start the local LiteRT-LM server if needed)")

    if failures:
        print(f"\nResult: {failures} required check(s) failed.")
        return 1
    print("\nResult: required environment checks passed; optional runtimes and real inference still need smoke tests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
