#!/usr/bin/env bash
# Opt-in per-user systemd startup for NOVA. No sudo; never exposes the API publicly.
set -euo pipefail
ACTION="${1:-install}"
ENABLE_LINGER=0
if [[ "${2:-}" == "--enable-linger" ]]; then ENABLE_LINGER=1; fi
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"

case "$ACTION" in
  install)
    if [[ "$(uname -s)" != Linux ]] || ! command -v systemctl >/dev/null 2>&1; then
      echo "Automatic startup installer requires Linux with systemd." >&2; exit 2
    fi
    if [[ ! -x "$ROOT/.venv/bin/python" && ! -f "$ROOT/.venv/Scripts/python.exe" ]]; then
      echo "NOVA virtual environment not found. Run the installer first: python scripts/install_all.py" >&2; exit 2
    fi
    cat > "$UNIT_DIR/nova-backend.service" <<EOF
[Unit]
Description=NOVA local-first agent API
After=network.target

[Service]
Type=simple
WorkingDirectory=$ROOT
ExecStart=/usr/bin/bash $ROOT/scripts/run_backend.sh
Restart=on-failure
RestartSec=5
UMask=0077

[Install]
WantedBy=default.target
EOF
    cat > "$UNIT_DIR/nova-frontend.service" <<EOF
[Unit]
Description=NOVA local web UI
After=network.target nova-backend.service

[Service]
Type=simple
WorkingDirectory=$ROOT
ExecStart=/usr/bin/bash $ROOT/scripts/run_frontend.sh
Restart=on-failure
RestartSec=5
UMask=0077

[Install]
WantedBy=default.target
EOF
    chmod 600 "$UNIT_DIR/nova-backend.service" "$UNIT_DIR/nova-frontend.service"
    systemctl --user daemon-reload
    systemctl --user enable --now nova-backend.service nova-frontend.service
    if [[ "$ENABLE_LINGER" == 1 ]]; then
      command -v loginctl >/dev/null 2>&1 || { echo "loginctl unavailable; units enabled for user login only." >&2; exit 2; }
      loginctl enable-linger "$USER"
      echo "User lingering enabled: services can start without an interactive login."
    else
      echo "Services enabled. For startup before user login after reboot, explicitly run: bash scripts/install_autostart.sh install --enable-linger"
    fi
    echo "NOVA services installed for this user. UI: http://127.0.0.1:5173"
    ;;
  uninstall)
    if command -v systemctl >/dev/null 2>&1; then
      systemctl --user disable --now nova-backend.service nova-frontend.service 2>/dev/null || true
      systemctl --user daemon-reload || true
    fi
    rm -f "$UNIT_DIR/nova-backend.service" "$UNIT_DIR/nova-frontend.service"
    echo "NOVA user services removed. User lingering (if enabled) was not changed."
    ;;
  status)
    systemctl --user --no-pager status nova-backend.service nova-frontend.service
    ;;
  *)
    echo "Usage: bash scripts/install_autostart.sh [install [--enable-linger]|uninstall|status]" >&2
    exit 2
    ;;
esac
