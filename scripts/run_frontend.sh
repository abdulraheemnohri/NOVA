#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/frontend"
if [[ ! -d node_modules ]]; then
  echo "Frontend dependencies missing. Run: npm install" >&2
  exit 1
fi
exec npm run dev -- --host "${NOVA_UI_HOST:-127.0.0.1}" --port "${NOVA_UI_PORT:-5173}"
