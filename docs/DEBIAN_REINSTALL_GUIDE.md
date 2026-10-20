# Complete NOVA reinstall guide — Debian / Android Debian proot

This guide reinstalls NOVA's application dependencies without deleting user data, SQLite databases, audit logs, model files, downloaded voices, or workspace files. It is intended for Debian/Ubuntu with `apt-get`, including Debian running inside a proot on Android. It is not a native Termux installer.

## 0. Before reinstalling

Open Debian terminal and inspect the environment and storage:

```bash
cd ~/NOVA 2>/dev/null || true
pwd
uname -a
cat /etc/os-release
df -h "$HOME"
free -h 2>/dev/null || true
```

If `~/NOVA` already exists, back up your local configuration and data before updating. This creates a timestamped backup outside the repository:

```bash
cd ~/NOVA
BACKUP="$HOME/nova-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP"
cp -a .env "$BACKUP/" 2>/dev/null || true
cp -a data "$BACKUP/" 2>/dev/null || true
printf 'Backup: %s\n' "$BACKUP"
```

Keep the backup path private because `.env` and `data/` may contain local credentials or tokens. Do not run `rm -rf data` or delete `.env` to troubleshoot.

## 1. Install Debian system packages

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git build-essential cmake pkg-config \
  python3 python3-venv python3-dev python3-pip nodejs npm \
  ffmpeg tesseract-ocr libjpeg-dev zlib1g-dev
```

If you are already root inside Debian, omit `sudo`. NOVA requires Python 3.11+ and Node.js 18+. Check before continuing:

```bash
python3 --version
node --version
npm --version
git --version
```

If Debian's packaged Python or Node.js is too old, install a compatible version for your distribution before continuing. Do not bypass the version check.

## 2. Fetch the current repository safely

For a fresh install:

```bash
cd ~
git clone https://github.com/abdulraheemnohri/NOVA.git
cd NOVA
git switch main
git pull --ff-only origin main
```

For an existing checkout, first inspect local changes and back them up; do not force-reset a working tree:

```bash
cd ~/NOVA
git status --short --branch
git fetch origin --prune
git switch main
git pull --ff-only origin main
```

If `git switch main` refuses because of local modifications, stop and save/commit those changes or use a separate fresh clone. Do not use `git reset --hard` as a reinstall shortcut.

> The Gemma-first/runtime changes are available only after their pull request is merged into `main`. If they are still under review, use the reviewed feature branch named in the PR instead of assuming `main` already contains them.

## 3. Install NOVA application dependencies

Run the repository's mobile-first Debian installer:

```bash
bash scripts/install_mobile_debian.sh
```

It creates/uses `.venv`, installs Python and frontend dependencies, creates required data directories, installs FFmpeg/Tesseract and selects the `mobile` runtime concurrency profile. It does **not** download Gemma model weights, Whisper model weights, or Piper voices.

If the script is missing on the current branch, do not copy a guessed version from memory. Update to the PR branch that contains it or follow the latest repository instructions.

## 4. Optional runtimes — install only what you need

Check free space before compiling or downloading large files:

```bash
df -h "$HOME"
du -sh data 2>/dev/null || true
bash scripts/install_mobile_debian.sh --help
```

Choose one or more options supported by the installer:

```bash
# LiteRT-LM CLI installer/adapter, if supported by this repo revision
bash scripts/install_mobile_debian.sh --with-litert-lm

# Optional speech-to-text CLI
bash scripts/install_mobile_debian.sh --with-whisper-cpp

# Optional local text-to-speech CLI
bash scripts/install_mobile_debian.sh --with-piper

# Optional ONNX Runtime Python package
bash scripts/install_mobile_debian.sh --with-onnx
```

The convenience option below installs all bundled optional tools and can use substantial temporary disk/CPU, especially while building Whisper:

```bash
bash scripts/install_mobile_debian.sh --all-runtimes
```

On a phone, prefer installing one capability at a time. Runtime binaries alone are not enough: Whisper needs a compatible model file; Piper needs a compatible voice `.onnx` and matching `.onnx.json` sidecar. Do not download arbitrary model artifacts or assume every Gemma format works with every runtime.

## 5. Configure the local LiteRT-LM server and model

NOVA's chat runtime is LiteRT-LM. The backend expects the locally configured OpenAI-compatible API endpoint, normally `http://127.0.0.1:9379/v1`. The exact LiteRT-LM CLI command depends on the installed release and model artifact; verify the CLI's own `--help` output and the repository's current runtime documentation rather than copying an unverified command.

Inspect local configuration without printing secrets:

```bash
grep -E '^(NOVA_RUNTIME_PROFILE|NOVA_LITERT_BASE_URL|NOVA_LITERT_MODEL)=' .env 2>/dev/null || true
```

Set the mobile profile in `.env`:

```bash
grep -v '^NOVA_RUNTIME_PROFILE=' .env > .env.tmp
printf '%s\n' 'NOVA_RUNTIME_PROFILE=mobile' >> .env.tmp
mv .env.tmp .env
chmod 600 .env
```

Start the LiteRT-LM server in its own terminal using the verified command for your installed version. Keep it running while using chat; the task-scoped lifecycle manager does not yet own or automatically stop the primary chat server. Start model files locally and keep external/cloud providers disabled for local-only operation.

## 6. Verify the installation

```bash
source .venv/bin/activate
bash scripts/check.sh
python scripts/doctor.py
```

Check that the local model endpoint is reachable:

```bash
curl --fail --silent --show-error --max-time 5 \
  http://127.0.0.1:9379/v1/models
```

If NOVA requires an API token, use the token stored in the local configured token file and the authenticated API method described by the repository. Do not paste the token into public issues or chat.

## 7. Start NOVA

Use two Debian terminal sessions. In terminal A:

```bash
cd ~/NOVA
source .venv/bin/activate
bash scripts/run_backend.sh
```

In terminal B:

```bash
cd ~/NOVA
bash scripts/run_frontend.sh
```

If the scripts are not present in the checked-out revision, inspect `README.md` for the launch command for that revision. Do not assume a service manager such as systemd is available inside Android proot.

## 8. Gemma-first behavior and runtime safety

NOVA should follow this order for every task:

1. **Check actual Gemma capability:** probe the selected Gemma 4 E4B artifact, LiteRT-LM build and request format. Model-family documentation alone is not proof that a specific local endpoint supports image/audio input or native function calling.
2. **Prefer Gemma built-ins:** use supported text, image, audio, reasoning and function-calling features before considering another runtime.
3. **Route by capability gap:** only choose Whisper, Piper, FFmpeg, Tesseract or another compatible local adapter when the task requires a capability not available or reliable in the current Gemma/LiteRT-LM setup.
4. **Avoid duplicate work:** do not launch an external adapter when Gemma already completed the task successfully.
5. **Start on demand:** run allowlisted task executables with bounded input sizes, timeouts and concurrency. Return the result to Gemma for interpretation/verification, then allow the child process to exit and clean temporary files.
6. **Fallback safely:** if an optional binary/model is missing, unsupported, times out or fails, report the issue and use only a verified available alternative. Never silently send user data to a cloud provider.
7. **Protect mobile resources:** default to `NOVA_RUNTIME_PROFILE=mobile` (one managed task at a time); monitor free storage, memory, CPU and thermal/battery behavior. Avoid loading multiple multi-billion-parameter models concurrently.
8. **Validate all tool calls:** use exact registered tool names and schemas, allowlist executable IDs, apply policy checks and approval gates for writes/destructive/privileged actions. Never execute model-generated shell strings or grant permissions because the model requested them.

The current lifecycle manager wraps selected task-scoped CLIs. It is not proof that every runtime is automatically selected by Gemma, and it does not stop the independently managed LiteRT-LM server. Verify the current implementation and API before relying on automatic routing.

## 9. Common problems

- **Python version too old:** install Python 3.11+ from a supported Debian repository/release, recreate `.venv`, then rerun the installer.
- **Node/npm too old:** install Node.js 18+ and rerun `npm --prefix frontend ci` through the installer.
- **No disk space:** stop; inspect `df -h` and `du -sh data`. Move/clean only files you identify and no longer need. Keep backups of model weights and databases.
- **LiteRT endpoint refused:** start the local LiteRT-LM server, verify its bind address/port and model load log, then retry `/v1/models`.
- **Whisper/Piper reports missing model:** install/configure a compatible local model or voice file; the installer intentionally does not download weights.
- **Permission error:** verify ownership and file permissions for the checkout and `data/`; avoid running the whole app as root unless required by your environment.
- **Android proot limitation:** systemd, hardware acceleration, native wheels and some compilers may not be available. A failed optional runtime must not prevent core NOVA from reporting which feature is unavailable.

## 10. Upgrade without losing data

```bash
cd ~/NOVA
git status --short --branch
git fetch origin --prune
git switch main
git pull --ff-only origin main
bash scripts/install_mobile_debian.sh
bash scripts/check.sh
python scripts/doctor.py
```

Do not remove `.env`, `data/`, SQLite databases, audit logs, model weights or voice files as part of routine upgrades.
