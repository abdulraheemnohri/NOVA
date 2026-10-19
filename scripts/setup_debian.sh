#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer targets Debian/Ubuntu (apt-get)." >&2
  exit 2
fi
if [[ "${EUID}" -eq 0 ]]; then SUDO=; else SUDO=sudo; fi
echo "Installing system packages for NOVA (no Docker; no model downloads)..."
$SUDO apt-get update
$SUDO apt-get install -y python3 python3-venv python3-pip python3-dev build-essential git curl ca-certificates nodejs npm

python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("NOVA requires Python 3.11 or newer; install a newer Python and retry.")
PY
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "Node.js and npm are required for the Web UI." >&2
  exit 1
fi
node -e 'if (Number(process.versions.node.split(".")[0]) < 18) process.exit(1)' || {
  echo "Node.js 18+ is required for Vite. Install a supported Node.js release and retry." >&2
  exit 1
}

python3 scripts/install_all.py --skip-system-runtimes
mkdir -p data/workspace data/models
chmod 700 data data/workspace data/models
echo "Setup complete. LiteRT-LM CLI is installed but not started; no model weights were downloaded."
echo "Run: bash scripts/run_backend.sh and, in another terminal, bash scripts/run_frontend.sh"
echo "For optional task runtimes, use scripts/install_optional_runtimes.py --help."
