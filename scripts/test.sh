#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -x .venv/bin/python ]]; then PYTHON=.venv/bin/python; else PYTHON=python3; fi
"$PYTHON" -m pytest -q
if [[ -d frontend/node_modules ]]; then
  npm --prefix frontend test
else
  echo "Skipping frontend tests: frontend/node_modules is missing. Run npm --prefix frontend install." >&2
fi
