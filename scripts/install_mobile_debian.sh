#!/usr/bin/env bash
# Mobile-first Debian installer. Installs NOVA core and task utilities, not model weights.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ALL_RUNTIMES=0
WITH_LITERT=0
WITH_WHISPER=0
WITH_PIPER=0
WITH_ONNX=0
for arg in "$@"; do
  case "$arg" in
    --all-runtimes) ALL_RUNTIMES=1 ;;
    --with-litert-lm) WITH_LITERT=1 ;;
    --with-whisper-cpp) WITH_WHISPER=1 ;;
    --with-piper) WITH_PIPER=1 ;;
    --with-onnx) WITH_ONNX=1 ;;
    --help|-h)
      cat <<'HELP'
Usage: bash scripts/install_mobile_debian.sh [options]
  (no option)       Core NOVA + FFmpeg + Tesseract/Pillow; mobile concurrency profile
  --with-litert-lm  Install LiteRT-LM CLI (primary chat runtime)
  --with-whisper-cpp Build whisper.cpp from pinned upstream tag v1.7.6
  --with-piper      Install Piper CLI package
  --with-onnx       Install ONNX Runtime + Pillow for optional task adapters
  --all-runtimes    Install all above runtimes (does not download model weights/voices)
Review available storage first. Building Whisper can take a long time and use temporary disk.
HELP
      exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done
if [[ "$ALL_RUNTIMES" == 1 ]]; then
  WITH_LITERT=1; WITH_WHISPER=1; WITH_PIPER=1; WITH_ONNX=1
fi
if [[ "$(uname -s)" != "Linux" ]] || ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer requires a Debian/Ubuntu Linux environment with apt-get." >&2
  echo "It is not a native Android/Termux installer; run it inside your Debian proot/container." >&2
  exit 2
fi
if [[ "$(id -u)" == "0" ]]; then
  SUDO=()
elif command -v sudo >/dev/null 2>&1; then
  SUDO=(sudo)
else
  echo "apt-get needs root privileges. Run as root or install sudo and retry." >&2
  exit 2
fi
"${SUDO[@]}" apt-get update
"${SUDO[@]}" apt-get install -y --no-install-recommends \
  ca-certificates curl git build-essential cmake pkg-config \
  python3 python3-venv python3-dev python3-pip \
  nodejs npm ffmpeg tesseract-ocr libjpeg-dev zlib1g-dev
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "NOVA requires Python 3.11+. This Debian release provides an older Python; upgrade Python first." >&2
  exit 2
fi
if ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 18 ? 0 : 1)'; then
  echo "NOVA requires Node.js 18+. Upgrade Node.js before installing frontend dependencies." >&2
  exit 2
fi
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip install 'Pillow>=10,<13'
if [[ -f frontend/package-lock.json ]]; then
  npm --prefix frontend ci --no-audit --no-fund
else
  npm --prefix frontend install --no-audit --no-fund
fi
mkdir -p data/workspace data/models data/logs
chmod 700 data
if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
fi
# Explicitly choose the low-memory profile without overwriting unrelated user settings.
.venv/bin/python - "$ROOT/.env" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
lines = [line for line in lines if not line.lstrip().startswith("NOVA_RUNTIME_PROFILE=")]
lines.append("NOVA_RUNTIME_PROFILE=mobile")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
path.chmod(0o600)
PY
if [[ "$WITH_LITERT" == 1 ]]; then
  .venv/bin/python scripts/install_optional_runtimes.py --litert-lm
fi
if [[ "$WITH_PIPER" == 1 ]]; then
  .venv/bin/python scripts/install_optional_runtimes.py --piper
fi
if [[ "$WITH_WHISPER" == 1 ]]; then
  .venv/bin/python scripts/install_optional_runtimes.py --whisper-cpp --whisper-tag v1.7.6
fi
if [[ "$WITH_ONNX" == 1 ]]; then
  .venv/bin/python -m pip install 'onnxruntime>=1.18,<2'
fi
cat <<'DONE'

NOVA mobile Debian dependencies installed.
- Runtime profile: mobile (one managed task runtime at a time)
- Core chat runtime: LiteRT-LM; no fallback runtime is selected automatically
- FFmpeg/Tesseract/Pillow installed for local audio conversion and OCR
- Optional runtime processes are launched only for a task and exit on completion/timeout
- Model weights and Piper voice files were NOT downloaded
Next:
  bash scripts/check.sh
  python scripts/doctor.py
  bash scripts/run_backend.sh
In a second terminal:
  bash scripts/run_frontend.sh
DONE
