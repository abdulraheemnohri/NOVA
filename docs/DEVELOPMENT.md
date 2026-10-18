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

## Optional local engines

The Runtimes page provides **Installation command previews** for the supported optional Debian/Ubuntu packages FFmpeg and Tesseract OCR + Pillow. These are display-only allowlisted commands: NOVA never executes package-manager commands, even if a legacy execution flag is set. Copy and review a command, then run it manually if desired. Whisper.cpp and Piper are external local executables and require compatible local model/voice files; they cannot be reliably installed on every CPU/OS through a generic apt command. Configure their paths in `.env`; run `bash scripts/check_optional_runtimes.sh` to inspect availability. ONNX Runtime can be installed with `python -m pip install -r requirements-optional.txt` when needed. The app's primary chat runtime remains LiteRT-LM; no optional runtime is an automatic chat fallback.

## LiteRT-LM slow-inference timeout

The LiteRT-LM chat request timeout defaults to 120 seconds. On slower CPU-only systems, set `NOVA_LITERT_CHAT_TIMEOUT_SECONDS` in the backend environment to an integer from 5 to 600 seconds, then restart the backend. For example:

```dotenv
NOVA_LITERT_CHAT_TIMEOUT_SECONDS=240
```

This setting controls how long NOVA waits for a single local chat response; it does not change the model's generation limit or fix a runtime that disconnects unexpectedly. Health/model-list checks retain a short timeout so the dashboard can report an unavailable server quickly. The timeout is environment-controlled rather than editable from the browser.

## Offline notes

The source archive produced by `scripts/package_source.sh` is not a fully offline installer. To install on a disconnected machine, pre-stage compatible Python wheels, npm package cache/lock data, the LiteRT-LM runtime and model, and any optional executable/model assets for the target architecture. Do not bundle `.env`, `data/api.token`, local databases, audit logs or personal workspace data.
