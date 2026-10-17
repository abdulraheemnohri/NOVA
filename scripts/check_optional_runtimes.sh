#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi
check_command() {
  local label="$1" command_name="$2"
  if command -v "$command_name" >/dev/null 2>&1; then
    printf 'OK   %-14s %s\n' "$label" "$(command -v "$command_name")"
  else
    printf 'MISS %-14s not installed (optional)\n' "$label"
  fi
}
check_file() {
  local label="$1" path="$2"
  if [[ -n "$path" && -f "$path" ]]; then printf 'OK   %-14s %s\n' "$label" "$path"
  else printf 'MISS %-14s configured model file not found\n' "$label"; fi
}
check_command "LiteRT-LM" "litert-lm"
check_command "whisper.cpp" "${NOVA_WHISPER_CLI_PATH:-whisper-cli}"
check_file "Whisper model" "${NOVA_WHISPER_MODEL_PATH:-}"
check_command "Piper TTS" "${NOVA_PIPER_CLI_PATH:-piper}"
check_file "Piper voice" "${NOVA_PIPER_MODEL_PATH:-}"
check_command "llama.cpp" "${NOVA_LLAMA_CPP_SERVER_PATH:-llama-server}"
echo "Inventory only: missing optional runtimes are not installed automatically."
