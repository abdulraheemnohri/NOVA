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


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def command_available(configured: str | None, fallback: str) -> str | None:
    candidate = configured or fallback
    if Path(candidate).is_file() and os.access(candidate, os.X_OK):
        return candidate
    return shutil.which(candidate)


def main() -> int:
    env = read_env_file(ROOT / ".env")
    env.update({key: value for key, value in os.environ.items() if key.startswith("NOVA_")})
    failures = 0
    print("NOVA environment doctor (read-only)")
    print(f"Repository: {ROOT}")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    if sys.version_info < (3, 11):  # noqa: UP036 -- report unsupported Python versions clearly
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

    if (ROOT / "frontend" / "package.json").is_file():
        print("OK frontend package manifest")
    else:
        print("WARN frontend/package.json is missing")

    print("OK .env exists (values hidden)" if (ROOT / ".env").is_file()
          else "WARN .env is missing; copy .env.example to .env before first run")

    for name in ("NOVA_WORKSPACE", "NOVA_DATABASE_PATH", "NOVA_AUDIT_PATH"):
        configured = env.get(name)
        if configured:
            path = Path(configured).expanduser()
            if not path.is_absolute():
                path = ROOT / path
            print(f"INFO {name}: {'exists' if path.exists() else 'not created yet'}")
        else:
            print(f"INFO {name}: using application default")

    commands = {
        "LiteRT-LM": ("NOVA_LITERT_CLI_PATH", "litert-lm"),
        "whisper.cpp": ("NOVA_WHISPER_CLI_PATH", "whisper-cli"),
        "Piper": ("NOVA_PIPER_CLI_PATH", "piper"),
        "llama.cpp (inventory only)": ("NOVA_LLAMA_CPP_SERVER_PATH", "llama-server"),
    }
    for label, (setting, fallback) in commands.items():
        resolved = command_available(env.get(setting), fallback)
        print(f"OK optional command {label}: {resolved}" if resolved
              else f"INFO optional command {label}: not found (may be unused)")

    for setting in ("NOVA_WHISPER_MODEL_PATH", "NOVA_PIPER_MODEL_PATH"):
        configured = env.get(setting)
        if configured:
            path = Path(configured).expanduser()
            if not path.is_absolute():
                path = ROOT / path
            print(f"OK {setting}: file exists" if path.is_file()
                  else f"WARN {setting}: configured file not found")

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
