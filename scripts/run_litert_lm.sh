#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$ROOT/.venv/bin/litert-lm"
if [[ ! -x "$CLI" ]]; then
  if command -v litert-lm >/dev/null 2>&1; then
    CLI="$(command -v litert-lm)"
  else
    echo "LiteRT-LM CLI is not installed. Run: python scripts/install_optional_runtimes.py --litert-lm" >&2
    exit 2
  fi
fi
echo "Starting LiteRT-LM on loopback 127.0.0.1:9379. Stop with Ctrl+C."
echo "This explicit command runs in the foreground; NOVA does not start it automatically."
exec "$CLI" serve --host 127.0.0.1 --port 9379
