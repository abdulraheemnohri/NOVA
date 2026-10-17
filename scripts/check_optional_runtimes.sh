#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

# Parse simple KEY=value config lines without sourcing .env as shell code.
get_setting() {
  local key="$1" fallback="$2" value=""
  if [[ -n "${!key:-}" ]]; then printf '%s' "${!key}"; return; fi
  if [[ -f "$ROOT/.env" ]]; then
    value="$(awk -F= -v key="$key" '$1 ~ "^[[:space:]]*" key "[[:space:]]*$" {sub(/^[^=]*=/, ""); gsub(/^[[:space:]\042]+|[[:space:]\042]+$/, ""); print; exit}' "$ROOT/.env")"
  fi
  printf '%s' "${value:-$fallback}"
}
check_command() {
  local label="$1" candidate="$2"
  if [[ -x "$candidate" && -f "$candidate" ]]; then
    printf 'OK   %-18s %s\n' "$label" "$candidate"
  elif command -v "$candidate" >/dev/null 2>&1; then
    printf 'OK   %-18s %s\n' "$label" "$(command -v "$candidate")"
  else
    printf 'MISS %-18s not installed (optional)\n' "$label"
  fi
}
check_file() {
  local label="$1" path="$2"
  if [[ -n "$path" && -f "$path" ]]; then printf 'OK   %-18s %s\n' "$label" "$path"
  else printf 'MISS %-18s configured model file not found\n' "$label"; fi
}
check_command "LiteRT-LM" "$(get_setting NOVA_LITERT_CLI_PATH litert-lm)"
check_command "whisper.cpp" "$(get_setting NOVA_WHISPER_CLI_PATH whisper-cli)"
check_file "Whisper model" "$(get_setting NOVA_WHISPER_MODEL_PATH "")"
check_command "Piper TTS" "$(get_setting NOVA_PIPER_CLI_PATH piper)"
check_file "Piper voice" "$(get_setting NOVA_PIPER_MODEL_PATH "")"
check_command "llama.cpp inventory" "$(get_setting NOVA_LLAMA_CPP_SERVER_PATH llama-server)"
echo "Inventory only: missing optional runtimes are not installed automatically."
