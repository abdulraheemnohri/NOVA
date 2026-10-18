# Development, dependencies and scripts

NOVA targets Python 3.11+ and Node.js 18+ on Debian/Ubuntu. It is local-first, uses SQLite by default, has no Docker requirement, and does not require a cloud AI key.

## Dependency files

- `requirements.txt`: core backend runtime packages. Kept aligned with `pyproject.toml`.
- `requirements-dev.txt`: core packages plus pytest, httpx and Ruff for development and CI.
- `requirements-optional.txt`: optional ONNX/document/image libraries for task-specific adapters. They are not required to start NOVA and do not enable chat inference through ONNX.
- `frontend/package.json`: frontend dependencies. Run npm commands from `frontend/` or use `npm --prefix frontend ...`.

Use an isolated environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
cp .env.example .env
npm --prefix frontend install
```

On Debian/Ubuntu, `bash scripts/setup_debian.sh` installs system prerequisites and dependencies. It does not download models or install Docker.

## Scripts

| Script | Purpose |
| --- | --- |
| `scripts/setup_debian.sh` | Debian/Ubuntu setup, Python venv, Python packages, frontend packages and local data directories |
| `scripts/run_backend.sh` | Starts FastAPI bound to loopback by default |
| `scripts/run_frontend.sh` | Starts Vite bound to loopback by default |
| `scripts/test.sh` | Runs backend tests and frontend tests when dependencies are installed |
| `scripts/check.sh` | Compile checks, pytest, pip dependency check, Ruff, frontend tests and production build |
| `scripts/nova-api.sh` | Calls the loopback API using `data/api.token` automatically; keeps the token out of command arguments and shell history |
| `scripts/doctor.py` | Read-only dependency, local endpoint and optional-runtime diagnostics; never prints token values |
| `scripts/check_optional_runtimes.sh` | Reports local CLI/model presence without installing or launching engines |
| `scripts/package_source.sh` | Builds a source archive while excluding local secrets, model data, virtualenv and caches |

Run scripts with `bash scripts/<name>.sh`; they are designed to work even when GitHub's file upload interface does not preserve executable bits. A Makefile provides shortcuts: `make setup`, `make backend`, `make frontend`, `make test`, `make check`, `make doctor`.

## Start and verify

Terminal 1:

```bash
bash scripts/run_backend.sh
```

Terminal 2:

```bash
bash scripts/run_frontend.sh
```

Then run `python scripts/doctor.py`, open the UI at `http://127.0.0.1:5173`, and paste the locally generated API token from `data/api.token` into the sign-in UI. Never publish that token or expose the API to a public interface.

For terminal API requests, use the token-aware helper so you do not need to add a bearer token to every command:

```bash
bash scripts/nova-api.sh GET /api/health
bash scripts/nova-api.sh GET /api/settings/preferences
bash scripts/nova-api.sh POST /api/chat '{"message":"Reply with exactly: NOVA_CHAT_OK","max_tokens":64}'
```

The helper reads `data/api.token` locally, accepts only loopback API base URLs, and never prints the token. You can pass a JSON body as the third argument or use `-` to read the body from standard input. It does not bypass NOVA's authentication or audit-integrity checks.

For backend tests without frontend dependencies, activate `.venv` and run `python -m pytest -q`. For the full local gate run `bash scripts/check.sh`.

## Automatic dependency and runtime installation

Use the cross-platform installer from the repository root:

```bash
python scripts/install_all.py
```

On Windows, use `py scripts/install_all.py` if that is how Python 3.11+ is registered. The installer recursively discovers every project-owned `requirements*.txt` file (excluding virtual environments, `node_modules`, Git metadata and generated build/cache folders), installs them into `.venv`, and installs the frontend dependencies from `frontend/package.json`. It also installs the supported system tools Node.js/npm, FFmpeg and Tesseract OCR using apt, dnf, pacman, Homebrew or winget when available. Use `--dry-run` to review the commands or `--skip-system-runtimes` to install Python/npm packages only.

The installer does not download model weights, voices, or execute runtime binaries. Whisper.cpp and Piper require compatible binaries and local model/voice assets, which vary by OS and CPU and must be configured explicitly. LiteRT-LM installation/server setup remains version-specific; configure and validate it using the instructions for the LiteRT-LM release used on the target device.

All installed runtimes remain idle until a feature explicitly needs one. The app must not launch every runtime at startup, and optional runtimes are never chat-inference fallbacks: LiteRT-LM remains the only chat-inference runtime. Independent eligible tasks may run concurrently, but each task should start/use only its designated runtime and avoid duplicate background processes.

## Optional local engines

The Runtimes page provides **Installation command previews** for supported optional Debian/Ubuntu packages FFmpeg and Tesseract OCR + Pillow. Those UI previews are display-only allowlisted commands: the web API never executes package-manager commands, even if a legacy execution flag is set. The separate operator-invoked `scripts/install_all.py` installer can install supported OS packages when run directly in a trusted local terminal. Review its plan with `--dry-run` first. Whisper.cpp and Piper are external local executables and require compatible local model/voice files; they cannot be reliably installed on every CPU/OS through a generic apt command. Configure their paths in `.env`; run `bash scripts/check_optional_runtimes.sh` to inspect availability. ONNX Runtime can be installed with `python -m pip install -r requirements-optional.txt` when needed. The app's primary chat runtime remains LiteRT-LM; no optional runtime is an automatic chat fallback.


## Optional runtime installation and model validation

The base installer deliberately installs dependencies and system tools without starting model processes or downloading model weights. After the base setup, use the explicit runtime installer for selected task runtimes:

```bash
# Install LiteRT-LM CLI into NOVA's .venv (primary chat runtime package)
python scripts/install_optional_runtimes.py --litert-lm

# Install Piper TTS into NOVA's .venv
python scripts/install_optional_runtimes.py --piper

# Build whisper.cpp from an explicitly pinned upstream tag
python scripts/install_optional_runtimes.py --whisper-cpp --whisper-tag v1.7.6

# Review commands without making changes
python scripts/install_optional_runtimes.py --litert-lm --piper --dry-run
```

Run only the options you need. The whisper.cpp build requires Git, CMake and a working C/C++ compiler; on Windows, install the Visual Studio C++ build tools separately. The installer does not download model weights or Piper voices. Set `NOVA_WHISPER_CLI_PATH`, `NOVA_WHISPER_MODEL_PATH`, `NOVA_PIPER_CLI_PATH`, and `NOVA_PIPER_MODEL_PATH` in `.env` to your local files.

NOVA's runtime inventory and `GET /api/runtimes/preflight` perform read-only checks. Whisper model files must be present, readable and plausibly sized; Piper requires a non-empty ONNX voice file and a valid JSON sidecar with a positive sample rate and phoneme map. These checks do not load model weights or guarantee hardware compatibility. The LiteRT-LM package installation does not select a model, start a server, or change the configured chat endpoint. Choose a supported model/server setup from the [official LiteRT-LM CLI installation guide](https://developers.google.com/edge/litert-lm/cli/installation) and usage documentation.

Installed runtimes remain idle until a feature needs them. Independent OCR/transcription jobs may run concurrently; NOVA does not launch every runtime at startup. LiteRT-LM remains the only chat-inference runtime, with no silent fallback to Piper, Whisper.cpp, ONNX, Transformers, or llama.cpp.

## LiteRT-LM slow-inference timeout

The LiteRT-LM chat request timeout defaults to 120 seconds. On slower CPU-only systems, set `NOVA_LITERT_CHAT_TIMEOUT_SECONDS` in the backend environment to an integer from 5 to 600 seconds, then restart the backend. For example:

```dotenv
NOVA_LITERT_CHAT_TIMEOUT_SECONDS=240
```

This setting controls how long NOVA waits for a single local chat response; it does not change the model's generation limit or fix a runtime that disconnects unexpectedly. Health/model-list checks retain a short timeout so the dashboard can report an unavailable server quickly. The timeout is environment-controlled rather than editable from the browser.

## Offline notes

The source archive produced by `scripts/package_source.sh` is not a fully offline installer. To install on a disconnected machine, pre-stage compatible Python wheels, npm package cache/lock data, the LiteRT-LM runtime and model, and any optional executable/model assets for the target architecture. Do not bundle `.env`, `data/api.token`, local databases, audit logs or personal workspace data.
