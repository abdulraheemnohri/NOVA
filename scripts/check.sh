#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -x .venv/bin/python ]]; then PYTHON=.venv/bin/python; else PYTHON=python3; fi
"$PYTHON" -m compileall -q backend tests scripts
bash -n scripts/*.sh
"$PYTHON" -m pytest -q
"$PYTHON" -m pip check
"$PYTHON" -m ruff check scripts
npm --prefix frontend test
npm --prefix frontend run build
echo "All configured checks passed."
