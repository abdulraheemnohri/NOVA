#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT/dist-packages}"
mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="$OUT_DIR/nova-source-$STAMP.tar.gz"
cd "$ROOT"
tar -czf "$ARCHIVE" \
  --exclude='./.git' \
  --exclude='./.venv' \
  --exclude='./.env' \
  --exclude='./data' \
  --exclude='./frontend/node_modules' \
  --exclude='./frontend/dist' \
  --exclude='./.pytest_cache' \
  --exclude='./.ruff_cache' \
  .
echo "Created source archive: $ARCHIVE"
echo "This is a source bundle, not a fully offline dependency/model bundle."
