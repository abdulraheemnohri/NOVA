#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -x .venv/bin/python ]]; then
  echo "Missing .venv. Run: bash scripts/setup_debian.sh (Debian/Ubuntu) or create a venv and install requirements-dev.txt." >&2
  exit 1
fi
if [[ ! -f .env ]]; then
  echo "Missing .env. Copy .env.example to .env and review the local settings first." >&2
  exit 1
fi
exec .venv/bin/python -m uvicorn nova.main:app --app-dir backend --host "${NOVA_HOST:-127.0.0.1}" --port "${NOVA_PORT:-8000}"
