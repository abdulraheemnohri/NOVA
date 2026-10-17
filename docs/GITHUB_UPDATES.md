# GitHub updater and reboot behavior

NOVA compares its installed commit with the official `abdulraheemnohri/NOVA` `main` commit. The updater is optional and all automatic behavior is off by default.

## Safe update contract
- Installation is allowed only from a clean Git checkout on `main` with an expected official GitHub `origin`.
- GitHub's reported SHA is compared with the fetched commit before a fast-forward.
- Backend tests and, when the frontend package lock exists, frontend dependency install, tests and production build run after updating.
- If validation fails after fast-forward, the checkout is reset to the previous commit and an audit event is recorded.
- The update code does not modify user database contents or model files as part of a Git operation. Back up the installation and data directory anyway.

## Automatic behavior
In **Updates**, choose automatic checks, automatic installation, interval, and reboot-after-update independently subject to required dependencies. Automatic install requires automatic checks; reboot requires automatic installation. The updater worker polls at the configured interval.

If reboot-after-update is enabled, Linux `systemctl reboot` is requested only after successful validation and only when the backend process is already privileged. NOVA never attempts privilege escalation. If reboot is disabled, the updater reports `restart_required: true`; the running API process must be restarted manually to load new code. Automatic reboot is unsupported on Windows and non-systemd systems.

## Operational limits
- A dirty working tree, unexpected branch/origin, non-fast-forward update, failed tests, or missing Git/npm prerequisites prevents successful installation.
- Keep automatic installation disabled on production until backups, maintenance windows and target-host tests are in place.
- Updates require internet access. The agent's normal LiteRT-LM chat path remains local-first; no cloud model fallback is introduced.
